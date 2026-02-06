# AWS Speech-to-Text API with Gemini Summarization

A Python API using Flask, AWS Transcribe for audio transcription, and Google Gemini 2.5 Flash for AI-powered transcript summarization.

## Features

- **Two transcription modes:**
  - **Real-time WebSocket streaming** (WebSocket) - True real-time transcription from mobile apps while user is recording, bi-directional streaming, no S3 required
  - **Async Batch mode** (`/transcribe-batch-async`) - Support for multiple audio formats via S3, non-blocking background processing
- **AI-powered summarization with Google Gemini 2.5 Flash:**
  - **Summary only** (`/summarize-transcript`) - Summarize existing transcripts
- Automatic cleanup of temporary files and S3 objects
- Simple REST API interface
- Support for multiple languages (transcription and summarization)

## Prerequisites

- Python 3.8+
- **AWS Account** (for transcription):
  - IAM user with access to Transcribe services
  - AWS credentials (Access Key ID and Secret Access Key)
  - S3 bucket (required for batch transcription and WebSocket real-time mode for audio archival)
- **Google API Key** (for summarization):
  - Required for `/summarize-transcript` endpoint
  - Get your API key from [Google AI Studio](https://aistudio.google.com/app/apikey)

## Setup

1. **Clone or navigate to the project directory**

2. **Create and activate virtual environment** (already created in `.venv`):
   ```bash
   source .venv/bin/activate  # On macOS/Linux
   # or
   .venv\Scripts\activate  # On Windows
   ```

3. **Install dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

4. **Configure API credentials**:
   - Copy `.env.example` to `.env`:
     ```bash
     cp .env.example .env
     ```
   - Edit `.env` and add your credentials:
     ```
     # AWS credentials (for transcription)
     AWS_ACCESS_KEY_ID=your_actual_access_key
     AWS_SECRET_ACCESS_KEY=your_actual_secret_key
     AWS_REGION=us-east-1
     S3_BUCKET_NAME=your-s3-bucket-name  # Required for batch endpoints

     # Google Gemini API (for summarization)
     GOOGLE_API_KEY=your_google_api_key_here
     ```

5. **Create S3 bucket** (for batch transcription only):
   - Create an S3 bucket in your AWS account
   - Ensure your IAM user has permissions to upload/delete objects in the bucket
   - Update `S3_BUCKET_NAME` in `.env` with your bucket name

## Usage

### Start the API server

```bash
python app.py
```

The server will start on `http://localhost:5001`

### Transcribe audio

#### Option 1: Real-Time WebSocket Streaming

**WebSocket Events:**
- **Client → Server:**
  - `start_transcription` - Start new session with `{language_code: 'en-US'}`
  - `audio_chunk` - Send audio chunk `{chunk: base64_encoded_pcm_data}`
  - `stop_transcription` - End session

- **Server → Client:**
  - `connected` - Connection established
  - `transcription_started` - Session ready, start sending audio
  - `transcription_result` - Real-time result `{text: '...', is_partial: true/false}`
  - `transcription_stopped` - Session ended
  - `error` - Error occurred `{message: '...'}`

**Audio Requirements:**
- Format: PCM (raw, uncompressed)
- Sample rate: 16000 Hz
- Channels: Mono (1)
- Bit depth: 16-bit
- Chunk size: 100-200ms worth of audio (~3200-6400 bytes)

---


#### Option 2: Async Batch Mode (Large files, multiple formats)

See [ASYNC_BATCH_API.md](ASYNC_BATCH_API.md) for full documentation on `/transcribe-batch-async`.

#### Option 3: Summarize Transcript (Text summarization only)

Using curl with JSON:

```bash
curl -X POST http://localhost:5001/summarize-transcript \
  -H "Content-Type: application/json" \
  -d '{"transcript": "Your transcript text here..."}'
```

Using curl with form data:

```bash
curl -X POST http://localhost:5001/summarize-transcript \
  -F "transcript=Your transcript text here..."
```

Using Python requests:

```python
import requests

url = "http://localhost:5001/summarize-transcript"
data = {"transcript": "Your transcript text here..."}

response = requests.post(url, json=data)
print(response.json())
```

With custom prompt:

```python
import requests

url = "http://localhost:5001/summarize-transcript"
data = {
    "transcript": "Your transcript text here...",
    "custom_prompt": "Summarize the following transcript in 3 bullet points: {transcript}"
}

response = requests.post(url, json=data)
print(response.json())
```

With summary language (Traditional Chinese):

```bash
curl -X POST http://localhost:5001/summarize-transcript \
  -H "Content-Type: application/json" \
  -d '{"transcript": "Your transcript text here...", "summary_language": "zh-HK"}'
```

```python
import requests

url = "http://localhost:5001/summarize-transcript"
data = {
    "transcript": "Your transcript text here...",
    "summary_language": "zh-HK"  # Options: zh-HK, zh-CN, en
}

response = requests.post(url, json=data)
print(response.json())
```

### Response format

Success response (streaming):
```json
{
  "success": true,
  "transcript": "This is the transcribed text from your audio file."
}
```


Success response (WebSocket realtime transcription stopped):
```json
{
  "success": true,
  "summary": "**Overall Summary**: This transcript discusses...\n\n**Key Points**:\n- Point 1\n- Point 2\n\n**Action Items**:\n- Task 1\n- Task 2",
  "model": "gemini-2.5-flash",
  "summary_language": "en",
  "transcript_length": 1523
}
```

Success response (WebSocket realtime transcription stopped):
```json
{
  "status": "success",
  "message": "Transcription session ended",
  "s3_url": "s3://bucket-name/audio/realtime/2026-02-04/session-xyz.pcm"
}
```

Error response:
```json
{
  "error": "Error message describing what went wrong"
}
```

## Supported Audio Formats

### WebSocket Real-Time
AWS Transcribe Streaming API supports **PCM audio format only**:
- **Format**: WAV files with PCM encoding
- **Sample Rate**: 16000 Hz recommended
- **Channels**: Mono (1)
- **Bit Depth**: 16-bit

### Async Batch Endpoint (`/transcribe-batch-async`)
AWS Transcribe Batch API supports **multiple audio formats**:
- **MP3** - MPEG Audio Layer III
- **MP4** - MPEG-4 container (audio only)
- **WAV** - Waveform Audio File Format
- **FLAC** - Free Lossless Audio Codec
- **OGG** - Ogg Vorbis
- **AMR** - Adaptive Multi-Rate
- **WebM** - WebM container (audio only)
- **M4A** - MPEG-4 Audio

**Note**: Other formats may require conversion before transcription.

## API Endpoints

### `POST /summarize-transcript` (AI Summarization)

Summarize an existing transcript using Google Gemini 2.5 Flash. **Requires Google API key.**

**Parameters:**
- `transcript` (required): The transcript text to summarize (JSON or form data)
- `summary_language` (optional): Language code for summary output. Defaults to `en`
  - `zh-HK` - Traditional Chinese (繁體中文)
  - `zh-CN` - Simplified Chinese (简体中文)
  - `en` - English
- `custom_prompt` (optional): Custom prompt template (use `{transcript}` as placeholder)

**Returns:**
- `200 OK`: Summarization successful
- `400 Bad Request`: No transcript provided
- `500 Internal Server Error`: Gemini API error or missing API key

**Response format**:
```json
{
  "success": true,
  "summary": "Structured summary with key points, action items, etc.",
  "model": "gemini-2.5-flash",
  "summary_language": "zh-HK",
  "transcript_length": 1523
}
```

**Default summary structure**:
1. **Overall Summary**: Concise overview (2-3 sentences)
2. **Key Points**: Main points discussed (bullet points)
3. **Action Items**: Tasks and decisions mentioned
4. **Important Details**: Dates, numbers, names, technical details

---

### `GET /health`

Health check endpoint.

**Returns:**
```json
{
  "status": "healthy"
}
```

## License

MIT
