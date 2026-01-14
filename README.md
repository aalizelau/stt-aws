# AWS Speech-to-Text API

A Python API using Flask and AWS Transcribe for audio transcription with two modes: streaming and batch processing.

## Features

- **Two transcription modes:**
  - **Streaming mode** (`/transcribe`) - Real-time PCM/WAV transcription, no S3 required
  - **Batch mode** (`/transcribe-batch`) - Support for multiple audio formats via S3
- Automatic cleanup of temporary files and S3 objects
- Simple REST API interface
- Support for multiple languages

## Prerequisites

- Python 3.8+
- AWS Account with:
  - IAM user with access to Transcribe services (Streaming API for `/transcribe`, Batch API for `/transcribe-batch`)
  - AWS credentials (Access Key ID and Secret Access Key)
  - S3 bucket (required only for batch transcription endpoint)

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

4. **Configure AWS credentials**:
   - Copy `.env.example` to `.env`:
     ```bash
     cp .env.example .env
     ```
   - Edit `.env` and add your AWS credentials:
     ```
     AWS_ACCESS_KEY_ID=your_actual_access_key
     AWS_SECRET_ACCESS_KEY=your_actual_secret_key
     AWS_REGION=us-east-1
     S3_BUCKET_NAME=your-s3-bucket-name  # Required for batch endpoint
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

### Transcribe an audio file

#### Option 1: Streaming Mode (PCM/WAV only, no S3 required)

Using curl:

```bash
curl -X POST http://localhost:5001/transcribe \
  -F "file=@/path/to/your/audio.wav" \
  -F "language_code=en-US"
```

Using Python requests:

```python
import requests

url = "http://localhost:5001/transcribe"
files = {"file": open("audio.wav", "rb")}
data = {"language_code": "en-US"}

response = requests.post(url, files=files, data=data)
print(response.json())
```

#### Option 2: Batch Mode (Multiple formats, requires S3)

Using curl:

```bash
curl -X POST http://localhost:5001/transcribe-batch \
  -F "file=@/path/to/your/audio.mp3" \
  -F "language_code=en-US"
```

Using Python requests:

```python
import requests

url = "http://localhost:5001/transcribe-batch"
files = {"file": open("audio.mp3", "rb")}
data = {"language_code": "en-US"}

response = requests.post(url, files=files, data=data)
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

Success response (batch):
```json
{
  "success": true,
  "transcript": "This is the transcribed text from your audio file.",
  "mode": "batch"
}
```

Error response:
```json
{
  "error": "Error message describing what went wrong"
}
```

## Supported Audio Formats

### Streaming Endpoint (`/transcribe`)
AWS Transcribe Streaming API supports **PCM audio format only**:
- **Format**: WAV files with PCM encoding
- **Sample Rate**: 8000, 16000, 24000, 32000, 44100, or 48000 Hz (16000 Hz recommended)
- **Channels**: Mono or stereo audio
- **Bit Depth**: 16-bit

### Batch Endpoint (`/transcribe-batch`)
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

## Supported Language Codes

Common examples:
- `en-US` - English (US)
- `en-GB` - English (UK)
- `es-ES` - Spanish (Spain)
- `fr-FR` - French (France)
- `de-DE` - German (Germany)
- `zh-CN` - Chinese (Mandarin)

See [AWS Transcribe documentation](https://docs.aws.amazon.com/transcribe/latest/dg/supported-languages.html) for full list.

## API Endpoints

### `POST /transcribe` (Streaming Mode)

Transcribe an audio file using real-time streaming API. **No S3 bucket required.**

**Supported Formats**: PCM/WAV only

**Parameters:**
- `file` (required): Audio file to transcribe (WAV/PCM format)
- `language_code` (optional): Language code, defaults to `en-US`

**Returns:**
- `200 OK`: Transcription successful
- `400 Bad Request`: Invalid request (no file provided)
- `500 Internal Server Error`: Transcription failed or server error

**Processing**: Files are temporarily saved locally and deleted after transcription.

---

### `POST /transcribe-batch` (Batch Mode)

Transcribe an audio file using AWS Transcribe batch API with S3 storage. **Requires S3 bucket.**

**Supported Formats**: MP3, MP4, WAV, FLAC, OGG, AMR, WebM, M4A

**Parameters:**
- `file` (required): Audio file to transcribe (any supported format)
- `language_code` (optional): Language code, defaults to `en-US`

**Returns:**
- `200 OK`: Transcription successful
- `400 Bad Request`: Invalid request (no file provided or unsupported format)
- `408 Request Timeout`: Transcription took longer than 5 minutes
- `500 Internal Server Error`: Transcription failed, S3 error, or server error

**Processing**:
1. File is uploaded to S3
2. Transcription job is started
3. Server polls for completion (max 5 minutes)
4. S3 file and transcription job are cleaned up automatically

---

### `GET /health`

Health check endpoint.

**Returns:**
```json
{
  "status": "healthy"
}
```

## Notes

### Streaming Mode (`/transcribe`)
- Uses AWS Transcribe **Streaming API** for real-time transcription
- Audio files are temporarily saved to local `temp/` directory and deleted after transcription
- **No S3 bucket required** - all processing is done locally
- Audio is streamed to AWS in chunks for efficient processing
- Only supports PCM/WAV format

### Batch Mode (`/transcribe-batch`)
- Uses AWS Transcribe **Batch API** for asynchronous transcription
- Files are uploaded to S3 and automatically deleted after processing
- **Requires S3 bucket** configured in environment variables
- Supports multiple audio formats (MP3, MP4, WAV, FLAC, OGG, AMR, WebM, M4A)
- May take longer for processing (polls every 5 seconds, max 5 minutes timeout)
- Transcription jobs are automatically cleaned up after completion

### Which endpoint to use?
- **Use streaming mode** (`/transcribe`) for:
  - Quick, real-time transcription
  - WAV/PCM files
  - When you don't want to set up S3

- **Use batch mode** (`/transcribe-batch`) for:
  - MP3, MP4, and other compressed audio formats
  - Longer audio files
  - When you already have S3 infrastructure

## Troubleshooting

**Missing environment variables:**
- Make sure your `.env` file exists and contains all required variables
- For streaming mode: `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_REGION`
- For batch mode: Also requires `S3_BUCKET_NAME`

**AWS credentials error:**
- Verify your AWS credentials are correct
- Ensure your IAM user has permissions for:
  - Amazon Transcribe Streaming API (for `/transcribe`)
  - Amazon Transcribe Batch API (for `/transcribe-batch`)
  - S3 permissions: `s3:PutObject`, `s3:GetObject`, `s3:DeleteObject` (for `/transcribe-batch`)

**S3 bucket error (batch mode):**
- Ensure the S3 bucket exists in your AWS account
- Verify the bucket name in `.env` is correct
- Check that your IAM user has S3 permissions for the bucket

**Audio format error:**
- **Streaming endpoint**: Ensure your audio file is in PCM/WAV format with 16kHz sample rate
- **Batch endpoint**: Check that your file format is supported (MP3, MP4, WAV, FLAC, OGG, AMR, WebM, M4A)
- Convert unsupported formats before uploading

**Timeout error (batch mode):**
- Transcription jobs have a 5-minute timeout
- For very long audio files, consider increasing `max_attempts` in [app.py:199](app.py#L199)

**Import errors:**
- Make sure you've installed all dependencies: `pip install -r requirements.txt`
- Activate the virtual environment before running the app

## License

MIT
