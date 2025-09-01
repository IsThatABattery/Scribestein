## Audio Stream Transcriber (Google Speech-to-Text v2)

This Python app streams live audio from a URL and transcribes it using Google Cloud Speech-to-Text API v2 (gRPC streaming). Final transcripts are appended to `transcript.log`.

### Prerequisites
- A Google Cloud project with the Speech-to-Text v2 API enabled
- A service account with access to Speech v2
- Service account key JSON file

### Setup
1. Create and activate a virtual environment:
```bash
python3 -m venv .venv
./.venv/bin/python -m pip install -U pip
./.venv/bin/pip install -r requirements.txt
```

2. Create a `.env` file in the project root (or copy from `.env.example`) and set required variables:
```env
GOOGLE_APPLICATION_CREDENTIALS=/absolute/path/to/your-service-account.json
GOOGLE_CLOUD_PROJECT=your-project-id
GCP_LOCATION=global
RECOGNIZER_ID=radio-stream-recognizer
STREAM_URL=https://broadcastify.cdnstream1.com/26933
LANGUAGE_CODE=en-US
MODEL=telephony
```

3. Run the transcriber:
```bash
./.venv/bin/python transcribe_stream.py
```

Transcripts will be printed to stdout and appended to `transcript.log`.

### Notes
- Uses v2 `StreamingRecognize` with `AutoDetectDecodingConfig` so no ffmpeg or pre-splitting is required.
- A v2 `Recognizer` resource is created automatically on first run if it does not exist.
- For radio/telephony-style audio, start with `MODEL=telephony`. You can experiment with other models as needed.


