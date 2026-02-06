# AWS Speech-to-Text API with Gemini Summarization

A Python API using Flask, AWS Transcribe, and Google Gemini 2.5 Flash.

> **Developer Documentation**: See [API_DOCS.md](API_DOCS.md) for detailed API usage, endpoints, and examples.

## Features

- **Real-time WebSocket streaming**: True real-time transcription for mobile apps (bi-directional).
- **Async Batch mode**: scalable background processing for large files (MP3, MP4, etc.) via S3.
- **AI Summarization**: Summarize transcripts using Google Gemini 2.5 Flash.
- **Auto-archival**: Audio files are automatically saved to S3.

## Prerequisites

- Python 3.8+
- **AWS Account**: Access to Transcribe and S3.
- **Google API Key**: For Gemini summarization.

## Setup

1.  **Install dependencies**:
    ```bash
    pip install -r requirements.txt
    ```

2.  **Configure `.env`**:
    ```ini
    AWS_ACCESS_KEY_ID=...
    AWS_SECRET_ACCESS_KEY=...
    AWS_REGION=us-east-1
    S3_BUCKET_NAME=your-bucket
    GOOGLE_API_KEY=your-key
    ```

3.  **Run the server**:
    ```bash
    python app.py
    ```
    Server starts at `http://44.223.62.169:5001`.

## Quick Start

### WebSocket (Real-Time)
Connect to `ws://44.223.62.169:5001/socket.io/`.
Emit `start_transcription` event, then stream `audio_chunk` events (PCM 16kHz).

### Async Batch
Upload file for background processing:
```bash
curl -X POST http://44.223.62.169:5001/transcribe-batch-async -F "file=@audio.mp3"
```

### Summarization
```bash
curl -X POST http://44.223.62.169:5001/summarize-transcript -d '{"transcript": "..."}' -H "Content-Type: application/json"
```

## License
MIT
