import os
import logging
import time
from typing import Generator, Iterable
import traceback
from datetime import datetime
import pytz

import requests
from dotenv import load_dotenv
from google.api_core.exceptions import AlreadyExists, GoogleAPICallError, RetryError
from google.cloud import speech_v2 as speech
from google.cloud.speech_v2.types import cloud_speech
from google.cloud import firestore


load_dotenv()

# Configure logging
# Transcript logger for successful transcriptions
transcript_logger = logging.getLogger("transcript")
transcript_logger.setLevel(logging.INFO)
t_handler = logging.FileHandler("transcript.log")
t_format = logging.Formatter("%(asctime)s - %(message)s")
t_handler.setFormatter(t_format)
transcript_logger.addHandler(t_handler)

# Error logger for application status and errors
error_logger = logging.getLogger("error")
error_logger.setLevel(logging.INFO)  # Capture info, warning, and error
e_handler = logging.FileHandler("error.log")
e_format = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
e_handler.setFormatter(e_format)
error_logger.addHandler(e_handler)

# Firestore client
db = None
firestore_collection = None
firestore_enabled = False
if "GOOGLE_APPLICATION_CREDENTIALS" in os.environ:
    try:
        database_id = os.getenv("FIRESTORE_DATABASE", "(default)")
        db = firestore.Client(database=database_id)
        firestore_collection = os.getenv("FIRESTORE_COLLECTION", "transcripts")
        firestore_enabled = True
        error_logger.info(
            "Firestore logging enabled to collection: %s in database: %s",
            firestore_collection,
            database_id,
        )
    except Exception as e:
        error_logger.warning(
            f"Could not initialize Firestore client: {e}. Firestore logging disabled."
        )
else:
    error_logger.info(
        "GOOGLE_APPLICATION_CREDENTIALS not set, Firestore logging disabled."
    )


def get_env(name: str, default: str | None = None) -> str:
    value = os.getenv(name, default)
    if value is None:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


def ensure_recognizer(client: speech.SpeechClient) -> str:
    """Get or create a v2 Recognizer and return its resource name."""
    project_id = get_env("GOOGLE_CLOUD_PROJECT")
    location = os.getenv("GCP_LOCATION", "global")
    recognizer_id = os.getenv("RECOGNIZER_ID", "radio-stream-recognizer")
    language_code = os.getenv("LANGUAGE_CODE", "en-US")
    model = os.getenv("MODEL", "telephony")

    parent = f"projects/{project_id}/locations/{location}"
    recognizer_name = f"{parent}/recognizers/{recognizer_id}"

    try:
        # Try to fetch existing recognizer
        recognizer = client.get_recognizer(name=recognizer_name)
        return recognizer.name
    except Exception:
        # Create if it does not exist
        recognizer = cloud_speech.Recognizer(
            language_codes=[language_code],
            model=model,
        )
        try:
            op = client.create_recognizer(
                parent=parent,
                recognizer=recognizer,
                recognizer_id=recognizer_id,
            )
            created = op.result()
            return created.name
        except AlreadyExists:
            # Race: created elsewhere
            return recognizer_name


def build_request_stream(recognizer_name: str, stream_url: str) -> Iterable[cloud_speech.StreamingRecognizeRequest]:
    """Yield the config request first, then audio chunk requests from the URL stream."""
    language_code = os.getenv("LANGUAGE_CODE", "en-US")
    model = os.getenv("MODEL", "telephony")

    # First request: recognizer + streaming config
    streaming_config = cloud_speech.StreamingRecognitionConfig(
        config=cloud_speech.RecognitionConfig(
            # Let v2 auto-detect input encoding/format from the bytes
            auto_decoding_config=cloud_speech.AutoDetectDecodingConfig(),
            language_codes=[language_code],
            # The model is inherited from the recognizer, so we don't need to specify it here.
            # model=model,
            # Enable punctuation for readability
            features=cloud_speech.RecognitionFeatures(
                enable_automatic_punctuation=True,
            ),
        ),
        # Enable interim results for faster feedback.
        # Note: only final results are logged.
        streaming_features=cloud_speech.StreamingRecognitionFeatures(
            interim_results=True,
        ),
    )

    yield cloud_speech.StreamingRecognizeRequest(
        recognizer=recognizer_name,
        streaming_config=streaming_config,
    )

    # Subsequent requests: audio bytes
    # Use a long/indefinite read timeout so idle periods on the source don't kill the iterator.
    # Also request no ICY metadata (common on radio streams) so only raw audio bytes are delivered.
    headers = {"Icy-MetaData": "0"}
    try:
        with requests.Session() as session:
            with session.get(
                stream_url,
                stream=True,
                timeout=(10, None),  # (connect, read) — None means no read timeout
                headers=headers,
            ) as response:
                response.raise_for_status()
                for chunk in response.iter_content(chunk_size=4096):
                    if not chunk:
                        continue
                    yield cloud_speech.StreamingRecognizeRequest(
                        audio=chunk,
                    )
    except requests.RequestException as req_err:
        # Log and end the iterator gracefully; outer loop will reconnect.
        error_logger.exception("Audio stream request failed: %s", req_err)
        return


def log_to_firestore(transcript: str, confidence: float) -> None:
    """Log a transcript and its confidence score to Firestore if enabled."""
    if not firestore_enabled or not db or not firestore_collection:
        return

    try:
        # Generate a timezone-aware timestamp for the document ID
        est = pytz.timezone("US/Eastern")
        now = datetime.now(est)
        # Format: YYYY-MM-DD_HH-MM-SS-ffffff_EST
        doc_id = now.strftime("%Y-%m-%d_%H-%M-%S-%f_%Z")

        doc_ref = db.collection(firestore_collection).document(doc_id)
        payload = {
            "timestamp": now,  # Use the same timezone-aware datetime object
            "transcript": transcript,
            "confidence": confidence,
        }
        doc_ref.set(payload)
    except Exception as e:
        error_logger.exception("Failed to write to Firestore: %s", e)


def transcribe_forever() -> None:
    """Continuously stream and transcribe, automatically restarting on recoverable errors."""
    location = os.getenv("GCP_LOCATION", "global")
    client_options = None
    if location != "global":
        client_options = {"api_endpoint": f"{location}-speech.googleapis.com"}

    client = speech.SpeechClient(client_options=client_options)
    recognizer_name = ensure_recognizer(client)
    stream_url = get_env("STREAM_URL")

    while True:
        try:
            requests_iter = build_request_stream(recognizer_name, stream_url)
            responses = client.streaming_recognize(requests=requests_iter)

            for response in responses:
                for result in response.results:
                    # Only commit final results to the log
                    if getattr(result, "is_final", False) and result.alternatives:
                        alternative = result.alternatives[0]
                        transcript = alternative.transcript.strip()
                        confidence = getattr(alternative, "confidence", 0.0)
                        if transcript:
                            transcript_logger.info(transcript)
                            print(transcript, flush=True)
                            log_to_firestore(transcript, confidence)

            # If the stream ends naturally, briefly pause and restart
            time.sleep(1)

        except (GoogleAPICallError, RetryError, requests.RequestException) as err:
            # Transient error: wait and restart
            error_logger.exception("Streaming error: %s", err)
            err_type = type(err).__name__
            print(f"Stream error: {err_type}: {err}. Reconnecting in 3s...", flush=True)
            time.sleep(3)
            continue
        except Exception as err:
            # Catch-all to surface clearer diagnostics instead of vague 'Exception iterating requests'
            error_logger.exception("Unexpected error in streaming loop: %s", err)
            err_type = type(err).__name__
            print(f"Unexpected stream error: {err_type}: {err}. Reconnecting in 3s...", flush=True)
            time.sleep(3)
            continue
        except KeyboardInterrupt:
            error_logger.info("User interrupted stream.")
            print("Interrupted by user.", flush=True)
            break


if __name__ == "__main__":
    transcribe_forever()


