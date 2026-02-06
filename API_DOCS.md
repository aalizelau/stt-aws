# API Documentation

## 1. Real-Time WebSocket Streaming

**Use case**: Mobile apps with live recording, true real-time transcription.

### Connection
- **URL**: `http://44.223.62.169:5001`
- **Path**: `/socket.io/`

### Events

| Direction | Event | Payload | Description |
|-----------|-------|---------|-------------|
| Client → Server | `start_transcription` | `{ "language_code": "en-US" }` | Session init. Options: `en-US`, `zh-HK`, `zh-CN` |
| Client → Server | `audio_chunk` | `{ "chunk": "base64..." }` | PCM data (16kHz, mono, 16-bit) |
| Client → Server | `stop_transcription` | `{}` | End session |
| Server → Client | `connected` | `{ "status": "..." }` | Connection success |
| Server → Client | `transcription_started` | `{ "message": "..." }` | Ready to stream |
| Server → Client | `transcription_result` | `{ "text": "...", "is_partial": bool }` | Real-time text |
| Server → Client | `transcription_stopped` | `{ "s3_url": "..." }` | Session ended, audio saved |

---

## 2. Async Batch Transcription

**Use case**: Large files, multiple formats (MP3, MP4, M4A, etc.), non-blocking.

### Start Job
`POST /transcribe-batch-async`

**Form Data:**
- `file`: Audio file (binary)
- `language_code`: `en-US` (default). Options: `en-US`, `zh-HK`, `zh-CN`

**Response (201):**
```json
{
  "job_name": "transcribe-uuid...",
  "status": "IN_PROGRESS",
  "status_endpoint": "/transcribe-job/transcribe-uuid..."
}
```

### Check Status
`GET /transcribe-job/<job_name>`

**Response (200):**
- **IN_PROGRESS**: `{"status": "IN_PROGRESS", "message": "..."}`
- **COMPLETED**: `{"status": "COMPLETED", "transcript": "...", "s3_url": "..."}`
- **FAILED**: `{"status": "FAILED", "failure_reason": "..."}`

### List Jobs
`GET /transcribe-jobs?status=COMPLETED&max_results=10`

---

## 3. Summarization

**Use case**: Summarize existing text transcripts with Google Gemini.

### Summarize
`POST /summarize-transcript` (Base URL: `http://44.223.62.169:5001`)

**JSON Body:**
```json
{
  "transcript": "Full text content...",
  "summary_language": "en",  // optional: en, zh-HK, zh-CN
  "custom_prompt": "Optional custom instruction..."
}
```

**Response (200):**
```json
{
  "success": true,
  "summary": "**Overall Summary**: ... \n**Key Points**: ...",
  "model": "gemini-2.5-flash"
}
```

---

## 4. Others

### Health Check
`GET http://44.223.62.169:5001/health`
