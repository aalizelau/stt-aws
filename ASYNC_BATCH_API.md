# Async Batch Transcription API

## Overview

AWS Transcribe provides **asynchronous batch transcription** as a native feature. This implementation exposes that capability through RESTful endpoints that allow you to:

1. Start transcription jobs that process in the background
2. Check job status at any time
3. Retrieve results when complete

This is much more scalable than the synchronous `/transcribe-batch` endpoint, which blocks the HTTP request until completion.

---

## Comparison: Sync vs Async

| Feature | `/transcribe-batch` (Sync) | `/transcribe-batch-async` (Async) |
|---------|----------------------------|-----------------------------------|
| **Request blocks?** | Yes (up to 5 minutes) | No (returns immediately) |
| **Scalability** | Limited (ties up server threads) | High (non-blocking) |
| **Client complexity** | Simple (one request) | Moderate (poll for status) |
| **Use case** | Small files, simple clients | Large files, mobile apps, batch processing |
| **Timeout risk** | High on slow networks | None (job runs independently) |

---

## API Endpoints

### 1. Start Async Transcription Job

**Endpoint:** `POST /transcribe-batch-async`

**Description:** Upload an audio file and start a transcription job. Returns immediately with job details.

**Request:**
```bash
curl -X POST http://localhost:5001/transcribe-batch-async \
  -F "file=@audio.mp3" \
  -F "language_code=en-US"
```

**Supported Audio Formats:**
- MP3, MP4, WAV, FLAC, OGG, AMR, WebM, M4A

**Request Parameters:**
- `file` (required): Audio file to transcribe
- `language_code` (optional): Language code (default: `en-US`)
  - Examples: `en-US`, `zh-CN`, `zh-HK`, `es-ES`, `fr-FR`

**Response (201 Created):**
```json
{
  "job_name": "transcribe-a1b2c3d4-5678-90ab-cdef-1234567890ab",
  "status": "IN_PROGRESS",
  "s3_url": "s3://your-bucket/audio/batch/2026-02-05/transcribe-a1b2c3d4-5678-90ab-cdef-1234567890ab.mp3",
  "upload_time_seconds": 0.45,
  "language_code": "en-US",
  "message": "Transcription job started. Use /transcribe-job/<job_name> to check status.",
  "status_endpoint": "/transcribe-job/transcribe-a1b2c3d4-5678-90ab-cdef-1234567890ab"
}
```

**Key Fields:**
- `job_name`: Unique identifier for the job (save this!)
- `status`: Initial status (usually `IN_PROGRESS`)
- `status_endpoint`: URL to check job status

---

### 2. Check Job Status

**Endpoint:** `GET /transcribe-job/<job_name>`

**Description:** Check the status of a transcription job and retrieve results if completed.

**Request:**
```bash
curl http://localhost:5001/transcribe-job/transcribe-a1b2c3d4-5678-90ab-cdef-1234567890ab
```

**Response - In Progress (200 OK):**
```json
{
  "job_name": "transcribe-a1b2c3d4-5678-90ab-cdef-1234567890ab",
  "status": "IN_PROGRESS",
  "language_code": "en-US",
  "creation_time": "2026-02-05T10:30:00.123456",
  "start_time": "2026-02-05T10:30:02.456789",
  "message": "Transcription is still in progress. Check again in a few seconds."
}
```

**Response - Completed (200 OK):**
```json
{
  "job_name": "transcribe-a1b2c3d4-5678-90ab-cdef-1234567890ab",
  "status": "COMPLETED",
  "language_code": "en-US",
  "creation_time": "2026-02-05T10:30:00.123456",
  "completion_time": "2026-02-05T10:31:15.789012",
  "transcript": "This is the transcribed text from your audio file...",
  "media_format": "mp3",
  "media_sample_rate_hz": 44100,
  "s3_url": "s3://your-bucket/audio/batch/2026-02-05/transcribe-a1b2c3d4-5678-90ab-cdef-1234567890ab.mp3"
}
```

**Response - Failed (200 OK):**
```json
{
  "job_name": "transcribe-a1b2c3d4-5678-90ab-cdef-1234567890ab",
  "status": "FAILED",
  "language_code": "en-US",
  "creation_time": "2026-02-05T10:30:00.123456",
  "failure_reason": "The media format is not supported"
}
```

**Response - Not Found (404):**
```json
{
  "error": "Job not found: transcribe-invalid-job-name",
  "message": "The transcription job does not exist or has been deleted."
}
```

**Job Statuses:**
- `QUEUED`: Job is waiting to start
- `IN_PROGRESS`: Job is currently processing
- `COMPLETED`: Job finished successfully (transcript available)
- `FAILED`: Job failed (see `failure_reason`)

---

### 3. List Recent Jobs

**Endpoint:** `GET /transcribe-jobs`

**Description:** List recent transcription jobs with optional filtering.

**Request:**
```bash
# List all recent jobs
curl http://localhost:5001/transcribe-jobs

# Filter by status
curl http://localhost:5001/transcribe-jobs?status=IN_PROGRESS
curl http://localhost:5001/transcribe-jobs?status=COMPLETED

# Limit results
curl http://localhost:5001/transcribe-jobs?max_results=10
```

**Query Parameters:**
- `status` (optional): Filter by status (`QUEUED`, `IN_PROGRESS`, `COMPLETED`, `FAILED`)
- `max_results` (optional): Max jobs to return (default: 20, max: 100)

**Response (200 OK):**
```json
{
  "jobs": [
    {
      "job_name": "transcribe-job-3",
      "status": "COMPLETED",
      "language_code": "en-US",
      "creation_time": "2026-02-05T10:30:00.123456",
      "start_time": "2026-02-05T10:30:02.456789",
      "completion_time": "2026-02-05T10:31:15.789012"
    },
    {
      "job_name": "transcribe-job-2",
      "status": "IN_PROGRESS",
      "language_code": "zh-CN",
      "creation_time": "2026-02-05T10:28:00.123456",
      "start_time": "2026-02-05T10:28:02.456789"
    },
    {
      "job_name": "transcribe-job-1",
      "status": "FAILED",
      "language_code": "en-US",
      "creation_time": "2026-02-05T10:25:00.123456",
      "failure_reason": "Insufficient audio data"
    }
  ],
  "count": 3,
  "filters": {
    "status": "all",
    "max_results": 20
  }
}
```

---

## Usage Examples

### Python

```python
import requests
import time

# 1. Start transcription job
with open('audio.mp3', 'rb') as f:
    response = requests.post(
        'http://localhost:5001/transcribe-batch-async',
        files={'file': f},
        data={'language_code': 'en-US'}
    )

job_name = response.json()['job_name']
print(f"Job started: {job_name}")

# 2. Poll for completion
while True:
    status_response = requests.get(
        f'http://localhost:5001/transcribe-job/{job_name}'
    )
    result = status_response.json()

    if result['status'] == 'COMPLETED':
        print(f"Transcript: {result['transcript']}")
        break
    elif result['status'] == 'FAILED':
        print(f"Failed: {result['failure_reason']}")
        break
    else:
        print(f"Status: {result['status']}")
        time.sleep(5)  # Wait 5 seconds before checking again
```

### cURL

```bash
# Start job
JOB_NAME=$(curl -X POST http://localhost:5001/transcribe-batch-async \
  -F "file=@audio.mp3" \
  -F "language_code=en-US" \
  | jq -r '.job_name')

echo "Job started: $JOB_NAME"

# Check status
while true; do
  STATUS=$(curl -s http://localhost:5001/transcribe-job/$JOB_NAME | jq -r '.status')
  echo "Status: $STATUS"

  if [ "$STATUS" == "COMPLETED" ]; then
    curl -s http://localhost:5001/transcribe-job/$JOB_NAME | jq -r '.transcript'
    break
  elif [ "$STATUS" == "FAILED" ]; then
    curl -s http://localhost:5001/transcribe-job/$JOB_NAME | jq -r '.failure_reason'
    break
  fi

  sleep 5
done
```

### JavaScript (Fetch API)

```javascript
// 1. Start transcription job
async function transcribeAsync(audioFile) {
  const formData = new FormData();
  formData.append('file', audioFile);
  formData.append('language_code', 'en-US');

  const response = await fetch('http://localhost:5001/transcribe-batch-async', {
    method: 'POST',
    body: formData
  });

  const { job_name } = await response.json();
  console.log(`Job started: ${job_name}`);

  // 2. Poll for completion
  while (true) {
    const statusResponse = await fetch(
      `http://localhost:5001/transcribe-job/${job_name}`
    );
    const result = await statusResponse.json();

    if (result.status === 'COMPLETED') {
      console.log('Transcript:', result.transcript);
      return result;
    } else if (result.status === 'FAILED') {
      console.error('Failed:', result.failure_reason);
      throw new Error(result.failure_reason);
    }

    console.log('Status:', result.status);
    await new Promise(resolve => setTimeout(resolve, 5000)); // Wait 5s
  }
}
```

---

## Test Script

Use the provided test script to test the async endpoints:

```bash
# Basic usage
python test_async_batch.py audio.mp3

# With specific language
python test_async_batch.py audio.mp3 zh-CN

# Different audio formats
python test_async_batch.py recording.wav en-US
python test_async_batch.py podcast.mp4 en-US
```

The script will:
1. Upload the audio file and start the job
2. Poll every 5 seconds until completion
3. Display the transcript when ready
4. List all recent jobs

---

## How It Works

### Architecture

```
Client                    Flask Server              AWS Transcribe
  |                            |                          |
  |-- POST /transcribe-batch-async ->|                    |
  |                            |-- start_transcription_job() ->
  |                            |                          |-- Queue job
  |<-- 201 (job_name) ---------|                          |
  |                            |                          |-- Process...
  |-- GET /transcribe-job/xxx ->|                        |
  |                            |-- get_transcription_job() ->
  |                            |                          |-- IN_PROGRESS
  |<-- 200 (IN_PROGRESS) ------|                          |
  |                            |                          |-- Process...
  |-- GET /transcribe-job/xxx ->|                        |
  |                            |-- get_transcription_job() ->
  |                            |                          |-- COMPLETED
  |<-- 200 (transcript) -------|                          |
```

### AWS Transcribe Job Lifecycle

1. **QUEUED**: Job submitted, waiting to start
2. **IN_PROGRESS**: Audio is being transcribed
3. **COMPLETED**: Transcription finished, results available
4. **FAILED**: Error occurred during processing

### Typical Processing Times

| Audio Length | Processing Time |
|--------------|----------------|
| 1 minute | 10-30 seconds |
| 5 minutes | 30-90 seconds |
| 30 minutes | 2-5 minutes |
| 1 hour | 5-10 minutes |

*Times vary based on audio quality, format, and AWS load*

---

## Best Practices

### 1. Polling Strategy

**Recommended polling intervals:**
- Start with 5-second intervals
- Increase to 10-15 seconds for longer jobs
- Implement exponential backoff for very long jobs

```python
def smart_poll(job_name, max_wait=300):
    """Poll with increasing intervals"""
    intervals = [3, 5, 5, 10, 10, 15, 15, 15]  # seconds
    elapsed = 0

    for interval in intervals:
        time.sleep(interval)
        elapsed += interval

        status = check_status(job_name)
        if status in ['COMPLETED', 'FAILED']:
            return status

        if elapsed >= max_wait:
            raise TimeoutError("Job took too long")
```

### 2. Error Handling

Always handle:
- Network failures (retry logic)
- Job failures (check `failure_reason`)
- Timeouts (jobs taking too long)
- Invalid job names (404 responses)

### 3. Job Cleanup

AWS Transcribe keeps job records for a limited time. For production:
- Store job names in your database
- Link jobs to user sessions
- Clean up old job records periodically

### 4. Scalability

**For high-volume applications:**
- Use a job queue (e.g., Redis, RabbitMQ)
- Implement webhooks instead of polling
- Monitor AWS Transcribe quotas
- Consider AWS Step Functions for workflow orchestration

---

## Production Considerations

### 1. Webhooks (Future Enhancement)

Instead of polling, AWS can notify you when jobs complete using SNS:

```python
# When starting job
transcribe_client.start_transcription_job(
    TranscriptionJobName=job_name,
    # ... other params ...
    Settings={
        'CompletionNotificationSNS': {
            'SnsTopicArn': 'arn:aws:sns:region:account:topic'
        }
    }
)
```

### 2. Job Persistence

Store job metadata in a database:

```sql
CREATE TABLE transcription_jobs (
    job_name VARCHAR(255) PRIMARY KEY,
    user_id INT,
    s3_url VARCHAR(500),
    status VARCHAR(50),
    language_code VARCHAR(10),
    created_at TIMESTAMP,
    completed_at TIMESTAMP,
    transcript TEXT
);
```

### 3. Rate Limiting

AWS Transcribe has quotas:
- **Batch jobs**: 250 concurrent jobs (default)
- **API calls**: 25 requests/second for `StartTranscriptionJob`

Implement rate limiting to stay within quotas.

### 4. Cost Optimization

- **Pricing**: $0.024 per minute (as of 2025)
- Delete old S3 audio files using lifecycle policies
- Use S3 Intelligent-Tiering for long-term storage
- Consider using `IdentifyLanguage` to avoid manual specification

---

## Troubleshooting

### Job stays IN_PROGRESS forever

**Causes:**
- AWS service issue
- Invalid audio format
- Audio file corrupted

**Solutions:**
- Check AWS Service Health Dashboard
- Verify audio file plays correctly
- Try re-uploading

### Job FAILED immediately

**Common reasons:**
- Unsupported audio format
- Audio too short (< 3 seconds)
- Invalid language code
- S3 permissions issue

**Check:**
```bash
# Get detailed failure reason
curl http://localhost:5001/transcribe-job/<job_name> | jq '.failure_reason'
```

### 404 Job Not Found

**Causes:**
- Job was deleted
- Job name typo
- Job expired (AWS keeps them for limited time)

---

## API Comparison Table

| Endpoint | Method | Purpose | Returns |
|----------|--------|---------|---------|
| `/transcribe-batch-async` | POST | Start async job | Job details (201) |
| `/transcribe-job/<name>` | GET | Check job status | Status + transcript if done (200) |
| `/transcribe-jobs` | GET | List recent jobs | Job list (200) |
| `/transcribe-batch` | POST | Sync transcription (legacy) | Transcript (200) |

---

## Further Reading

- [AWS Transcribe Batch API Documentation](https://docs.aws.amazon.com/transcribe/latest/APIReference/API_StartTranscriptionJob.html)
- [AWS Transcribe Pricing](https://aws.amazon.com/transcribe/pricing/)
- [Supported Languages](https://docs.aws.amazon.com/transcribe/latest/dg/supported-languages.html)
- [Best Practices for AWS Transcribe](https://docs.aws.amazon.com/transcribe/latest/dg/best-practices.html)
