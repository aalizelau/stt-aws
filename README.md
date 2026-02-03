# AWS Speech-to-Text API with Gemini Summarization

A Python API using Flask, AWS Transcribe for audio transcription, and Google Gemini 2.5 Flash for AI-powered transcript summarization.

## Features

- **Three transcription modes:**
  - **Standard streaming** (`/transcribe`) - Real-time PCM/WAV transcription, returns full transcript at once, no S3 required
  - **SSE streaming** (`/transcribe-stream`) - Real-time PCM/WAV transcription with **progressive results** via Server-Sent Events, no S3 required
  - **Batch mode** (`/transcribe-batch`) - Support for multiple audio formats via S3, with timing metrics
- **AI-powered summarization with Google Gemini 2.5 Flash:**
  - **Summary only** (`/summarize-transcript`) - Summarize existing transcripts
  - **Combined** (`/transcribe-and-summarize`) - Transcribe audio and generate summary in one call
- Automatic cleanup of temporary files and S3 objects
- Simple REST API interface
- Support for multiple languages (transcription and summarization)

## Prerequisites

- Python 3.8+
- **AWS Account** (for transcription):
  - IAM user with access to Transcribe services (Streaming API for `/transcribe`, Batch API for `/transcribe-batch`)
  - AWS credentials (Access Key ID and Secret Access Key)
  - S3 bucket (required only for batch transcription endpoints: `/transcribe-batch` and `/transcribe-and-summarize`)
- **Google API Key** (for summarization):
  - Required for `/summarize-transcript` and `/transcribe-and-summarize` endpoints
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

#### Option 2: Streaming Mode with Real-Time Results (PCM/WAV only, no S3 required)

Get transcription results **as they are generated** using Server-Sent Events (SSE):

Using curl (with real-time streaming):

```bash
curl -X POST http://localhost:5001/transcribe-stream \
  -F "file=@/path/to/your/audio.wav" \
  -F "language_code=en-US" \
  --no-buffer
```

Using Python with SSE client:

```python
import requests

url = "http://localhost:5001/transcribe-stream"
files = {"file": open("audio.wav", "rb")}
data = {"language_code": "en-US"}

# Stream the response
response = requests.post(url, files=files, data=data, stream=True)

for line in response.iter_lines():
    if line:
        line = line.decode('utf-8')
        if line.startswith('data: '):
            import json
            data = json.loads(line[6:])  # Remove 'data: ' prefix

            if data.get('done'):
                print("\n✓ Transcription complete!")
                break
            else:
                # Print partial or final results in real-time
                marker = "🔄" if data.get('is_partial') else "✓"
                print(f"{marker} {data['text']}")
```

Using JavaScript in browser:

```javascript
const formData = new FormData();
formData.append('file', audioFile);
formData.append('language_code', 'en-US');

const eventSource = await fetch('http://localhost:5001/transcribe-stream', {
    method: 'POST',
    body: formData
});

const reader = eventSource.body.getReader();
const decoder = new TextDecoder();

while (true) {
    const {done, value} = await reader.read();
    if (done) break;

    const chunk = decoder.decode(value);
    const lines = chunk.split('\n');

    for (const line of lines) {
        if (line.startsWith('data: ')) {
            const data = JSON.parse(line.substring(6));

            if (data.done) {
                console.log('✓ Transcription complete!');
            } else {
                console.log(data.is_partial ? '🔄' : '✓', data.text);
            }
        }
    }
}
```

**Response format (SSE):**
```
data: {"text": "hello", "is_partial": true}

data: {"text": "hello world", "is_partial": false}

data: {"text": "how are you", "is_partial": false}

data: {"done": true}
```

#### Option 3: Batch Mode (Multiple formats, requires S3)

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

#### Option 4: Summarize Transcript (Text summarization only)

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

#### Option 5: Transcribe and Summarize (Combined - audio to summary)

Using curl:

```bash
curl -X POST http://localhost:5001/transcribe-and-summarize \
  -F "file=@/path/to/your/audio.mp3" \
  -F "language_code=en-US"
```

With custom summary prompt:

```bash
curl -X POST http://localhost:5001/transcribe-and-summarize \
  -F "file=@/path/to/your/audio.mp3" \
  -F "language_code=zh-CN" \
  -F "custom_prompt=Focus on action items and key decisions: {transcript}"
```

Using Python requests:

```python
import requests

url = "http://localhost:5001/transcribe-and-summarize"
files = {"file": open("audio.mp3", "rb")}
data = {"language_code": "en-US"}

response = requests.post(url, files=files, data=data)
result = response.json()

print("Transcript:", result['transcript'])
print("\nSummary:", result['summary'])
print("\nProcessing Time:", result['total_processing_time_seconds'], "seconds")
```

### Response format

Success response (streaming):
```json
{
  "success": true,
  "transcript": "This is the transcribed text from your audio file."
}
```

Success response (batch with timing):
```json
{
  "success": true,
  "transcript": "This is the transcribed text from your audio file.",
  "mode": "batch",
  "upload_time_seconds": 0.34,
  "total_processing_time_seconds": 12.56
}
```

Success response (summarize only):
```json
{
  "success": true,
  "summary": "**Overall Summary**: This transcript discusses...\n\n**Key Points**:\n- Point 1\n- Point 2\n\n**Action Items**:\n- Task 1\n- Task 2",
  "model": "gemini-2.0-flash-exp",
  "transcript_length": 1523
}
```

Success response (transcribe and summarize):
```json
{
  "success": true,
  "transcript": "This is the transcribed text from your audio file.",
  "summary": "**Overall Summary**: This transcript discusses...\n\n**Key Points**:\n- Point 1\n- Point 2",
  "mode": "batch",
  "model": "gemini-2.0-flash-exp",
  "transcript_length": 1523,
  "upload_time_seconds": 0.34,
  "total_processing_time_seconds": 15.82
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

### `POST /transcribe-stream` (SSE Streaming Mode)

Transcribe an audio file using real-time streaming API with **progressive results** via Server-Sent Events. **No S3 bucket required.**

**Supported Formats**: PCM/WAV only

**Parameters:**
- `file` (required): Audio file to transcribe (WAV/PCM format)
- `language_code` (optional): Language code, defaults to `en-US`

**Returns (Server-Sent Events):**
- Stream of events in SSE format
- Each event contains: `{"text": "...", "is_partial": true/false}`
- Final event: `{"done": true}`

**Response format:**
```
data: {"text": "partial text", "is_partial": true}

data: {"text": "final text for phrase", "is_partial": false}

data: {"done": true}
```

**Processing**:
- Files are temporarily saved locally and deleted after transcription
- Results are streamed in real-time as AWS Transcribe generates them
- Partial results show intermediate recognition (may change)
- Final results are confirmed and won't change

**Use cases:**
- Real-time transcription display
- Live captioning
- Interactive voice applications
- Progress feedback for long audio files

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

**Response includes timing metrics**:
- `upload_time_seconds`: Time to upload file to S3
- `total_processing_time_seconds`: Total time from request to response

---

### `POST /summarize-transcript` (AI Summarization)

Summarize an existing transcript using Google Gemini 2.5 Flash. **Requires Google API key.**

**Parameters:**
- `transcript` (required): The transcript text to summarize (JSON or form data)
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
  "model": "gemini-2.0-flash-exp",
  "transcript_length": 1523
}
```

**Default summary structure**:
1. **Overall Summary**: Concise overview (2-3 sentences)
2. **Key Points**: Main points discussed (bullet points)
3. **Action Items**: Tasks and decisions mentioned
4. **Important Details**: Dates, numbers, names, technical details

**Example with custom prompt**:
```json
{
  "transcript": "Your transcript here...",
  "custom_prompt": "Summarize in 3 bullet points: {transcript}"
}
```

---

### `POST /transcribe-and-summarize` (Combined)

Transcribe audio and generate AI summary in one call. **Requires both S3 bucket and Google API key.**

**Supported Formats**: MP3, MP4, WAV, FLAC, OGG, AMR, WebM, M4A

**Parameters:**
- `file` (required): Audio file to transcribe (any supported format)
- `language_code` (optional): Language code, defaults to `en-US`
- `custom_prompt` (optional): Custom prompt template for summarization

**Returns:**
- `200 OK`: Both transcription and summarization successful
- `400 Bad Request`: Invalid file or unsupported format
- `408 Request Timeout`: Transcription took longer than 5 minutes
- `500 Internal Server Error`: Transcription, summarization, or S3 error

**Response format**:
```json
{
  "success": true,
  "transcript": "Full transcript text",
  "summary": "AI-generated summary",
  "mode": "batch",
  "model": "gemini-2.0-flash-exp",
  "transcript_length": 1523,
  "upload_time_seconds": 0.34,
  "total_processing_time_seconds": 15.82
}
```

**Processing**:
1. File is uploaded to S3
2. AWS Transcribe processes the audio
3. Google Gemini generates summary from transcript
4. S3 file and transcription job are cleaned up
5. Returns both transcript and summary with timing metrics

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
- **Use standard streaming mode** (`/transcribe`) for:
  - Quick, real-time transcription with single response
  - WAV/PCM files
  - When you don't want to set up S3
  - Simple use cases where you just need the final transcript

- **Use SSE streaming mode** (`/transcribe-stream`) for:
  - Real-time progressive transcription results
  - Live captioning or interactive applications
  - WAV/PCM files
  - When you want to show transcription progress to users
  - No S3 setup required

- **Use batch mode** (`/transcribe-batch`) for:
  - MP3, MP4, and other compressed audio formats
  - Longer audio files
  - When you already have S3 infrastructure

## Troubleshooting

**Missing environment variables:**
- Make sure your `.env` file exists and contains all required variables
- For streaming mode (`/transcribe`): `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_REGION`
- For batch mode (`/transcribe-batch`): Also requires `S3_BUCKET_NAME`
- For summarization (`/summarize-transcript`, `/transcribe-and-summarize`): Also requires `GOOGLE_API_KEY`

**AWS credentials error:**
- Verify your AWS credentials are correct
- Ensure your IAM user has permissions for:
  - Amazon Transcribe Streaming API (for `/transcribe`)
  - Amazon Transcribe Batch API (for `/transcribe-batch` and `/transcribe-and-summarize`)
  - S3 permissions: `s3:PutObject`, `s3:GetObject`, `s3:DeleteObject` (for batch endpoints)

**Google API key error:**
- Get your API key from [Google AI Studio](https://aistudio.google.com/app/apikey)
- Verify `GOOGLE_API_KEY` is set correctly in `.env` file
- Check that the API key has access to Gemini models
- Error message: "Google Gemini API not configured" means the key is missing

**S3 bucket error (batch mode):**
- Ensure the S3 bucket exists in your AWS account
- Verify the bucket name in `.env` is correct
- Check that your IAM user has S3 permissions for the bucket

**Audio format error:**
- **Streaming endpoint** (`/transcribe`): Ensure your audio file is in PCM/WAV format with 16kHz sample rate
- **Batch endpoints** (`/transcribe-batch`, `/transcribe-and-summarize`): Check that your file format is supported (MP3, MP4, WAV, FLAC, OGG, AMR, WebM, M4A)
- Convert unsupported formats before uploading

**Timeout error (batch mode):**
- Transcription jobs have a 5-minute timeout
- For very long audio files, consider increasing `max_attempts` in the code
- Check `total_processing_time_seconds` in response to monitor performance

**Import errors:**
- Make sure you've installed all dependencies: `pip install -r requirements.txt`
- Activate the virtual environment before running the app
- If you see "Cannot import google.generativeai", run `pip install google-generativeai`

## License

MIT
