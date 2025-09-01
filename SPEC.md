## Spec

### Current Features
- Stream audio from a live HTTP source defined by `STREAM_URL`.
- Transcribe using Google Speech-to-Text API v2 (gRPC streaming), no ffmpeg or chunking.
- Auto-detect input audio encoding/format using v2 `AutoDetectDecodingConfig`.
- Log final transcripts to `transcript.log` with timestamps.
- Store final transcripts and confidence scores in a Firestore collection, using a timezone-aware timestamp as the document ID.
- Minimal code footprint in a single main script (`transcribe_stream.py`).
- Configuration via `.env` for easy future containerization.

### Configuration (.env)
- `GOOGLE_APPLICATION_CREDENTIALS`: Absolute path to service account JSON
- `GOOGLE_CLOUD_PROJECT`: GCP project ID
- `GCP_LOCATION`: GCP location for Speech v2 resources (default `global`)
- `RECOGNIZER_ID`: Stable name for the v2 Recognizer resource
- `STREAM_URL`: Live audio URL to transcribe
- `LANGUAGE_CODE`: BCP-47 language code (e.g., `en-US`)
- `MODEL`: Recognition model (e.g., `telephony`)
- `FIRESTORE_DATABASE`: (Optional) Firestore database name (default `(default)`)
- `FIRESTORE_COLLECTION`: (Optional) Firestore collection to store transcripts (default `transcripts`)

### Future Enhancements
- Graceful rotation/recreation of the streaming call before service time-limit.
- Optional storage of raw responses for post-processing.
- Expose health/status metrics and simple HTTP readiness endpoint.
- Optional WebSocket broadcast to display live captions.
- Switchable diarization/speaker labels when suitable.
- Configurable profanity filtering and punctuation features.


