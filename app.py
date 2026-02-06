import os
import asyncio
import uuid
import time
import json
import urllib.request
from pathlib import Path
from flask import Flask, request, jsonify, Response, stream_with_context
from flask_socketio import SocketIO, emit, disconnect
from amazon_transcribe.client import TranscribeStreamingClient
from amazon_transcribe.handlers import TranscriptResultStreamHandler
from amazon_transcribe.model import TranscriptEvent
from dotenv import load_dotenv
import google.generativeai as genai

# Load environment variables with explicit path
env_path = Path(__file__).parent / '.env'
load_dotenv(dotenv_path=env_path)

# Debug: Verify environment variables are loaded
print("=" * 50)
print("Environment Variables Status:")
print(f"AWS_ACCESS_KEY_ID: {'SET' if os.getenv('AWS_ACCESS_KEY_ID') else 'NOT SET'}")
print(f"AWS_SECRET_ACCESS_KEY: {'SET' if os.getenv('AWS_SECRET_ACCESS_KEY') else 'NOT SET'}")
print(f"AWS_SESSION_TOKEN: {'SET' if os.getenv('AWS_SESSION_TOKEN') else 'NOT SET'}")
print(f"AWS_REGION: {os.getenv('AWS_REGION', 'NOT SET')}")
print(f"S3_BUCKET_NAME: {os.getenv('S3_BUCKET_NAME', 'NOT SET')}")
print(f"GOOGLE_API_KEY: {'SET' if os.getenv('GOOGLE_API_KEY') else 'NOT SET'}")
print(f".env file path: {env_path}")
print(f".env file exists: {env_path.exists()}")
print("=" * 50)

app = Flask(__name__)
app.config['JSON_AS_ASCII'] = False  # Display Chinese characters properly in JSON

# Initialize SocketIO for WebSocket support
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='eventlet')

# S3 client for batch transcription
import boto3

# Build AWS client configuration (supports both permanent and temporary credentials)
aws_config = {
    'aws_access_key_id': os.getenv('AWS_ACCESS_KEY_ID'),
    'aws_secret_access_key': os.getenv('AWS_SECRET_ACCESS_KEY'),
    'region_name': os.getenv('AWS_REGION', 'us-east-1')
}

# Add session token if present (for temporary credentials from STS)
if os.getenv('AWS_SESSION_TOKEN'):
    aws_config['aws_session_token'] = os.getenv('AWS_SESSION_TOKEN')
    print("Using temporary AWS credentials (with session token)")
else:
    print("Using permanent AWS credentials (no session token)")

s3_client = boto3.client('s3', **aws_config)
S3_BUCKET = os.getenv('S3_BUCKET_NAME')

# AWS Transcribe client for batch jobs
transcribe_client = boto3.client('transcribe', **aws_config)


# Helper function to convert S3 URLs to browser-accessible HTTPS URLs
def s3_to_https_url(s3_url, region=None):
    """
    Convert s3:// URL to browser-accessible HTTPS URL.

    Example:
        s3://bucket/path/file.mp3 -> https://bucket.s3.us-east-1.amazonaws.com/path/file.mp3

    Args:
        s3_url: S3 URL in format s3://bucket/key
        region: AWS region (defaults to AWS_REGION env var)

    Returns:
        HTTPS URL that can be opened in browsers
    """
    if not s3_url or not s3_url.startswith('s3://'):
        return s3_url

    # Get region from parameter or environment
    if region is None:
        region = os.getenv('AWS_REGION', 'us-east-1')

    # Parse s3://bucket/path/to/file
    parts = s3_url[5:].split('/', 1)  # Remove 's3://' prefix
    bucket = parts[0]
    key = parts[1] if len(parts) > 1 else ''

    # Return HTTPS URL
    return f"https://{bucket}.s3.{region}.amazonaws.com/{key}"

# Configure Google Gemini API
GOOGLE_API_KEY = os.getenv('GOOGLE_API_KEY')
if GOOGLE_API_KEY:
    genai.configure(api_key=GOOGLE_API_KEY)
    print("Google Gemini API configured successfully")
else:
    print("Warning: GOOGLE_API_KEY not set. Summarization endpoints will not work.")

# Create temp directory for uploaded files
TEMP_DIR = 'temp'
os.makedirs(TEMP_DIR, exist_ok=True)

# Language code mappings for summary output
SUMMARY_LANGUAGE_MAP = {
    'zh-HK': 'Traditional Chinese (繁體中文)',
    'zh-CN': 'Simplified Chinese (简体中文)',
    'en': 'English'
}

# Session management for real-time transcription
class RealtimeEventHandler(TranscriptResultStreamHandler):
    """Event handler that emits transcription results via WebSocket"""
    def __init__(self, transcript_result_stream, session_id):
        super().__init__(transcript_result_stream)
        self.session_id = session_id

    async def handle_transcript_event(self, transcript_event: TranscriptEvent):
        results = transcript_event.transcript.results
        for result in results:
            for alt in result.alternatives:
                # Emit to the specific client via SocketIO
                socketio.emit('transcription_result', {
                    'text': alt.transcript,
                    'is_partial': result.is_partial
                }, room=self.session_id)


class TranscriptionSession:
    """Manages a real-time transcription session for a WebSocket connection"""
    def __init__(self, session_id, language_code='en-US'):
        self.session_id = session_id
        self.language_code = language_code
        self.client = None
        self.stream = None
        self.handler = None
        self.is_active = False
        self.audio_buffer = []  # Buffer to store all audio chunks for S3 upload
        self.s3_key = None  # S3 key where audio will be saved
        self.start_timestamp = time.time()  # For organizing files by date

    async def start(self):
        """Initialize AWS Transcribe streaming session"""
        self.client = TranscribeStreamingClient(region=os.getenv('AWS_REGION', 'us-east-1'))
        self.stream = await self.client.start_stream_transcription(
            language_code=self.language_code,
            media_sample_rate_hz=16000,
            media_encoding='pcm',
        )
        self.handler = RealtimeEventHandler(self.stream.output_stream, self.session_id)
        self.is_active = True

        # Generate S3 key with date folder structure
        from datetime import datetime
        date_folder = datetime.fromtimestamp(self.start_timestamp).strftime('%Y-%m-%d')
        self.s3_key = f"audio/realtime/{date_folder}/session-{self.session_id}.pcm"

        # Start handling events in background
        asyncio.create_task(self.handler.handle_events())

    async def send_audio_chunk(self, chunk):
        """Send audio chunk to AWS Transcribe and buffer for S3"""
        if self.is_active and self.stream:
            # Buffer the chunk for later S3 upload
            self.audio_buffer.append(chunk)

            # Send to AWS Transcribe for real-time transcription
            await self.stream.input_stream.send_audio_event(audio_chunk=chunk)

    async def save_to_s3(self):
        """Upload buffered audio to S3"""
        if not self.audio_buffer:
            print(f"No audio to save for session {self.session_id}")
            return None

        if not S3_BUCKET:
            print(f"S3_BUCKET not configured, skipping audio save for session {self.session_id}")
            return None

        try:
            # Combine all chunks into single audio file
            complete_audio = b''.join(self.audio_buffer)

            # Upload to S3
            s3_client.put_object(
                Bucket=S3_BUCKET,
                Key=self.s3_key,
                Body=complete_audio,
                ContentType='audio/pcm'
            )

            s3_url = f"s3://{S3_BUCKET}/{self.s3_key}"
            print(f"Audio saved to S3: {s3_url} ({len(complete_audio):,} bytes)")

            return s3_url

        except Exception as e:
            print(f"Error saving audio to S3: {e}")
            return None

    async def stop(self):
        """Close the transcription stream"""
        if self.is_active and self.stream:
            await self.stream.input_stream.end_stream()
            self.is_active = False

# Global session storage (in production, use Redis or similar)
active_sessions = {}


class MyEventHandler(TranscriptResultStreamHandler):
    """Custom handler to collect transcription results"""
    def __init__(self, transcript_result_stream):
        super().__init__(transcript_result_stream)
        self.transcript_parts = []

    async def handle_transcript_event(self, transcript_event: TranscriptEvent):
        results = transcript_event.transcript.results
        for result in results:
            if not result.is_partial:
                for alt in result.alternatives:
                    self.transcript_parts.append(alt.transcript)


class StreamingEventHandler(TranscriptResultStreamHandler):
    """Event handler that streams transcription results to a queue for real-time SSE"""
    def __init__(self, transcript_result_stream, result_queue):
        super().__init__(transcript_result_stream)
        self.result_queue = result_queue

    async def handle_transcript_event(self, transcript_event: TranscriptEvent):
        results = transcript_event.transcript.results
        for result in results:
            for alt in result.alternatives:
                # Put both partial and final results in the queue
                await self.result_queue.put({
                    'text': alt.transcript,
                    'is_partial': result.is_partial
                })


async def transcribe_file_async(audio_file_path, language_code='en-US'):
    """
    Async function to transcribe audio using AWS Transcribe Streaming API
    """
    client = TranscribeStreamingClient(region=os.getenv('AWS_REGION', 'us-east-1'))

    # Read audio file
    async def audio_stream():
        with open(audio_file_path, 'rb') as audio_file:
            chunk_size = 1024 * 8  # 8KB chunks
            while True:
                chunk = audio_file.read(chunk_size)
                if not chunk:
                    break
                yield chunk
                await asyncio.sleep(0.01)  # Small delay to simulate streaming

    # Start streaming transcription
    stream = await client.start_stream_transcription(
        language_code=language_code,
        media_sample_rate_hz=16000,  # Adjust based on your audio
        media_encoding='pcm',
    )

    # Create event handler
    handler = MyEventHandler(stream.output_stream)

    # Send audio and handle events concurrently
    await asyncio.gather(
        write_chunks(stream, audio_stream()),
        handler.handle_events()
    )

    # Return combined transcript
    return ' '.join(handler.transcript_parts)


async def write_chunks(stream, audio_stream):
    """Write audio chunks to the stream"""
    async for chunk in audio_stream:
        await stream.input_stream.send_audio_event(audio_chunk=chunk)
    await stream.input_stream.end_stream()


async def transcribe_file_streaming(audio_file_path, language_code, result_queue):
    """
    Async function to transcribe audio with streaming results sent to a queue.
    This enables real-time Server-Sent Events (SSE) to clients.
    """
    client = TranscribeStreamingClient(region=os.getenv('AWS_REGION', 'us-east-1'))

    # Read audio file
    async def audio_stream():
        with open(audio_file_path, 'rb') as audio_file:
            chunk_size = 1024 * 8  # 8KB chunks
            while True:
                chunk = audio_file.read(chunk_size)
                if not chunk:
                    break
                yield chunk
                await asyncio.sleep(0.01)  # Small delay to simulate streaming

    # Start streaming transcription
    stream = await client.start_stream_transcription(
        language_code=language_code,
        media_sample_rate_hz=16000,
        media_encoding='pcm',
    )

    # Create streaming event handler
    handler = StreamingEventHandler(stream.output_stream, result_queue)

    try:
        # Send audio and handle events concurrently
        await asyncio.gather(
            write_chunks(stream, audio_stream()),
            handler.handle_events()
        )
    finally:
        # Signal completion
        await result_queue.put({'done': True})


@app.route('/transcribe-stream', methods=['POST'])
def transcribe_audio_stream():
    """
    Streaming endpoint that returns real-time transcription results via Server-Sent Events (SSE).
    Accepts audio file upload and streams transcription text as it's generated.
    """
    temp_file_path = None

    try:
        # Check if file is present
        if 'file' not in request.files:
            return jsonify({'error': 'No file provided'}), 400

        file = request.files['file']

        if file.filename == '':
            return jsonify({'error': 'No file selected'}), 400

        # Save file temporarily to local disk
        temp_filename = f"audio_{uuid.uuid4()}{os.path.splitext(file.filename)[1]}"
        temp_file_path = os.path.join(TEMP_DIR, temp_filename)
        file.save(temp_file_path)

        # Get language code from request
        language_code = request.form.get('language_code', 'en-US')

        # Generator function for SSE streaming
        def generate():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

            # Create async queue for streaming results (must be in same event loop)
            result_queue = asyncio.Queue()

            # Start transcription in background
            transcription_task = loop.create_task(
                transcribe_file_streaming(temp_file_path, language_code, result_queue)
            )

            try:
                while True:
                    # Get result from queue (blocking)
                    result = loop.run_until_complete(result_queue.get())

                    # Send SSE formatted data with readable unicode (ensure_ascii=False)
                    yield f"data: {json.dumps(result, ensure_ascii=False)}\n\n"

                    # Check if transcription is complete
                    if result.get('done'):
                        break
            finally:
                # Wait for transcription task to finish
                loop.run_until_complete(transcription_task)
                loop.close()

                # Clean up temp file
                if temp_file_path and os.path.exists(temp_file_path):
                    os.remove(temp_file_path)

        return Response(
            stream_with_context(generate()),
            mimetype='text/event-stream; charset=utf-8',
            headers={
                'Cache-Control': 'no-cache',
                'X-Accel-Buffering': 'no',  # Disable nginx buffering
                'Content-Type': 'text/event-stream; charset=utf-8'
            }
        )

    except Exception as e:
        # Clean up temp file on error
        if temp_file_path and os.path.exists(temp_file_path):
            os.remove(temp_file_path)

        return jsonify({'error': str(e)}), 500


@app.route('/transcribe', methods=['POST'])
def transcribe_audio():
    """
    Synchronous endpoint to transcribe audio file using local processing.
    Accepts audio file upload and returns transcription text.
    """
    temp_file_path = None

    try:
        # Check if file is present
        if 'file' not in request.files:
            return jsonify({'error': 'No file provided'}), 400

        file = request.files['file']

        if file.filename == '':
            return jsonify({'error': 'No file selected'}), 400

        # Save file temporarily to local disk
        import uuid
        temp_filename = f"audio_{uuid.uuid4()}{os.path.splitext(file.filename)[1]}"
        temp_file_path = os.path.join(TEMP_DIR, temp_filename)
        file.save(temp_file_path)

        # Get language code from request
        language_code = request.form.get('language_code', 'en-US')

        # Run async transcription in sync context
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        transcript_text = loop.run_until_complete(
            transcribe_file_async(temp_file_path, language_code)
        )
        loop.close()

        # Clean up temp file
        if temp_file_path and os.path.exists(temp_file_path):
            os.remove(temp_file_path)

        return jsonify({
            'success': True,
            'transcript': transcript_text
        }), 200

    except Exception as e:
        # Clean up temp file on error
        if temp_file_path and os.path.exists(temp_file_path):
            os.remove(temp_file_path)

        return jsonify({'error': str(e)}), 500


@app.route('/transcribe-batch-async', methods=['POST'])
def transcribe_audio_batch_async():
    """
    Async batch transcription endpoint using AWS Transcribe with S3.
    Supports multiple audio formats: MP3, MP4, WAV, FLAC, OGG, AMR, WebM.
    Starts the transcription job and returns immediately with job details.
    Use /transcribe-job/<job_name> to check status and retrieve results.
    """
    try:
        # Check if S3 bucket is configured
        if not S3_BUCKET:
            return jsonify({'error': 'S3_BUCKET_NAME not configured in environment variables'}), 500

        # Check if file is present
        if 'file' not in request.files:
            return jsonify({'error': 'No file provided'}), 400

        file = request.files['file']

        if file.filename == '':
            return jsonify({'error': 'No file selected'}), 400

        # Generate unique job name and S3 key with date folder
        from datetime import datetime
        date_folder = datetime.now().strftime('%Y-%m-%d')
        job_name = f"transcribe-{uuid.uuid4()}"
        file_extension = os.path.splitext(file.filename)[1].lstrip('.')
        s3_key = f"audio/batch/{date_folder}/{job_name}.{file_extension}"

        # Validate file format
        supported_formats = ['mp3', 'mp4', 'wav', 'flac', 'ogg', 'amr', 'webm', 'm4a']
        if file_extension.lower() not in supported_formats:
            return jsonify({
                'error': f'Unsupported file format: {file_extension}. Supported formats: {", ".join(supported_formats)}'
            }), 400

        # Upload file to S3
        upload_start = time.time()
        s3_client.upload_fileobj(file, S3_BUCKET, s3_key)
        upload_time = time.time() - upload_start

        # Start transcription job (non-blocking)
        file_uri = f"s3://{S3_BUCKET}/{s3_key}"

        response = transcribe_client.start_transcription_job(
            TranscriptionJobName=job_name,
            Media={'MediaFileUri': file_uri},
            MediaFormat=file_extension.lower(),
            LanguageCode=request.form.get('language_code', 'en-US')
        )

        # Return job details immediately
        job_status = response['TranscriptionJob']['TranscriptionJobStatus']

        return jsonify({
            'job_name': job_name,
            'status': job_status,
            'audio_url': s3_to_https_url(file_uri),
            'upload_time_seconds': round(upload_time, 2),
            'language_code': request.form.get('language_code', 'en-US'),
            'message': 'Transcription job started. Use /transcribe-job/<job_name> to check status.',
            'status_endpoint': f'/transcribe-job/{job_name}'
        }), 201

    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/transcribe-job/<job_name>', methods=['GET'])
def get_transcription_job_status(job_name):
    """
    Check the status of a transcription job and retrieve results if completed.

    Returns:
    - IN_PROGRESS: Job is still processing
    - COMPLETED: Job finished successfully, transcript included
    - FAILED: Job failed, failure reason included
    """
    try:
        response = transcribe_client.get_transcription_job(
            TranscriptionJobName=job_name
        )

        job = response['TranscriptionJob']
        status = job['TranscriptionJobStatus']

        result = {
            'job_name': job_name,
            'status': status,
            'language_code': job.get('LanguageCode'),
            'creation_time': job.get('CreationTime').isoformat() if job.get('CreationTime') else None,
        }

        if status == 'COMPLETED':
            # Get transcript
            transcript_uri = job['Transcript']['TranscriptFileUri']

            # Fetch transcript from URI
            with urllib.request.urlopen(transcript_uri) as url:
                transcript_data = json.loads(url.read().decode())

            transcript_text = transcript_data['results']['transcripts'][0]['transcript']

            # Add transcript and metadata
            result['transcript'] = transcript_text
            result['completion_time'] = job.get('CompletionTime').isoformat() if job.get('CompletionTime') else None
            result['media_format'] = job.get('MediaFormat')
            result['media_sample_rate_hz'] = job.get('MediaSampleRateHertz')

            # Get audio URL from media URI and convert to HTTPS
            media_uri = job.get('Media', {}).get('MediaFileUri')
            if media_uri:
                result['audio_url'] = s3_to_https_url(media_uri)

            return jsonify(result), 200

        elif status == 'FAILED':
            result['failure_reason'] = job.get('FailureReason', 'Unknown error')
            return jsonify(result), 200

        elif status == 'IN_PROGRESS':
            result['start_time'] = job.get('StartTime').isoformat() if job.get('StartTime') else None
            result['message'] = 'Transcription is still in progress. Check again in a few seconds.'
            return jsonify(result), 200

        else:
            # Handle any other status (e.g., QUEUED)
            result['message'] = f'Job status: {status}'
            return jsonify(result), 200

    except transcribe_client.exceptions.BadRequestException:
        return jsonify({
            'error': f'Job not found: {job_name}',
            'message': 'The transcription job does not exist or has been deleted.'
        }), 404
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/transcribe-jobs', methods=['GET'])
def list_transcription_jobs():
    """
    List recent transcription jobs with optional filtering.

    Query parameters:
    - status: Filter by status (QUEUED, IN_PROGRESS, COMPLETED, FAILED)
    - max_results: Maximum number of jobs to return (default: 20, max: 100)
    """
    try:
        # Get query parameters
        status_filter = request.args.get('status')
        max_results = min(int(request.args.get('max_results', 20)), 100)

        # Build list_transcription_jobs parameters
        list_params = {
            'MaxResults': max_results
        }

        if status_filter:
            valid_statuses = ['QUEUED', 'IN_PROGRESS', 'COMPLETED', 'FAILED']
            if status_filter.upper() not in valid_statuses:
                return jsonify({
                    'error': f'Invalid status filter. Must be one of: {", ".join(valid_statuses)}'
                }), 400
            list_params['Status'] = status_filter.upper()

        # List jobs
        response = transcribe_client.list_transcription_jobs(**list_params)

        # Format job summaries
        jobs = []
        for job_summary in response.get('TranscriptionJobSummaries', []):
            job_info = {
                'job_name': job_summary.get('TranscriptionJobName'),
                'status': job_summary.get('TranscriptionJobStatus'),
                'language_code': job_summary.get('LanguageCode'),
                'creation_time': job_summary.get('CreationTime').isoformat() if job_summary.get('CreationTime') else None,
                'start_time': job_summary.get('StartTime').isoformat() if job_summary.get('StartTime') else None,
                'completion_time': job_summary.get('CompletionTime').isoformat() if job_summary.get('CompletionTime') else None,
            }

            # Add failure reason if failed
            if job_summary.get('FailureReason'):
                job_info['failure_reason'] = job_summary.get('FailureReason')

            jobs.append(job_info)

        result = {
            'jobs': jobs,
            'count': len(jobs),
            'filters': {
                'status': status_filter if status_filter else 'all',
                'max_results': max_results
            }
        }

        # Add next token if available (for pagination)
        if 'NextToken' in response:
            result['next_token'] = response['NextToken']
            result['message'] = 'More results available. Use next_token parameter to fetch next page.'

        return jsonify(result), 200

    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/transcribe-batch', methods=['POST'])
def transcribe_audio_batch():
    """
    Batch transcription endpoint using AWS Transcribe with S3.
    Supports multiple audio formats: MP3, MP4, WAV, FLAC, OGG, AMR, WebM.
    Accepts audio file upload and returns transcription text.

    NOTE: This is a synchronous endpoint that waits for completion.
    For async behavior, use /transcribe-batch-async instead.
    """
    # Start timing
    start_time = time.time()

    try:
        # Check if S3 bucket is configured
        if not S3_BUCKET:
            return jsonify({'error': 'S3_BUCKET_NAME not configured in environment variables'}), 500

        # Check if file is present
        if 'file' not in request.files:
            return jsonify({'error': 'No file provided'}), 400

        file = request.files['file']

        if file.filename == '':
            return jsonify({'error': 'No file selected'}), 400

        # Generate unique job name and S3 key with date folder
        from datetime import datetime
        date_folder = datetime.now().strftime('%Y-%m-%d')
        job_name = f"transcribe-{uuid.uuid4()}"
        file_extension = os.path.splitext(file.filename)[1].lstrip('.')
        s3_key = f"audio/batch/{date_folder}/{job_name}.{file_extension}"

        # Validate file format
        supported_formats = ['mp3', 'mp4', 'wav', 'flac', 'ogg', 'amr', 'webm', 'm4a']
        if file_extension.lower() not in supported_formats:
            return jsonify({
                'error': f'Unsupported file format: {file_extension}. Supported formats: {", ".join(supported_formats)}'
            }), 400

        # Upload file to S3
        s3_client.upload_fileobj(file, S3_BUCKET, s3_key)
        upload_time = time.time() - start_time

        # Start transcription job
        file_uri = f"s3://{S3_BUCKET}/{s3_key}"

        transcribe_client.start_transcription_job(
            TranscriptionJobName=job_name,
            Media={'MediaFileUri': file_uri},
            MediaFormat=file_extension.lower(),
            LanguageCode=request.form.get('language_code', 'en-US')
        )

        # Wait for transcription to complete (polling)
        max_attempts = 60  # Maximum 5 minutes (60 * 5 seconds)
        attempt = 0

        while attempt < max_attempts:
            response = transcribe_client.get_transcription_job(
                TranscriptionJobName=job_name
            )

            status = response['TranscriptionJob']['TranscriptionJobStatus']

            if status == 'COMPLETED':
                # Get transcript
                transcript_uri = response['TranscriptionJob']['Transcript']['TranscriptFileUri']

                # Fetch transcript from URI
                with urllib.request.urlopen(transcript_uri) as url:
                    transcript_data = json.loads(url.read().decode())

                transcript_text = transcript_data['results']['transcripts'][0]['transcript']

                # Clean up transcription job (keep S3 file for archival)
                transcribe_client.delete_transcription_job(TranscriptionJobName=job_name)

                # Calculate total processing time
                total_time = time.time() - start_time

                # Generate audio URL (HTTPS format)
                s3_url = f"s3://{S3_BUCKET}/{s3_key}"
                audio_url = s3_to_https_url(s3_url)

                return jsonify({
                    'transcript': transcript_text,
                    'mode': 'batch',
                    'upload_time_seconds': round(upload_time, 2),
                    'total_processing_time_seconds': round(total_time, 2),
                    'audio_url': audio_url
                }), 200

            elif status == 'FAILED':
                failure_reason = response['TranscriptionJob'].get('FailureReason', 'Unknown error')

                # Note: S3 file kept even on failure for debugging

                return jsonify({
                    'error': f'Transcription failed: {failure_reason}'
                }), 500

            # Still in progress, wait before checking again
            time.sleep(5)
            attempt += 1

        # Timeout - S3 file kept for manual inspection

        return jsonify({
            'error': 'Transcription timeout. Job may still be processing.'
        }), 408

    except Exception as e:
        return jsonify({'error': str(e)}), 500


# Old S3-based implementation (commented out for reference)
# @app.route('/transcribe', methods=['POST'])
# def transcribe_audio():
#     """
#     Synchronous endpoint to transcribe audio file.
#     Accepts audio file upload and returns transcription text.
#     """
#     try:
#         # Check if file is present
#         if 'file' not in request.files:
#             return jsonify({'error': 'No file provided'}), 400
#
#         file = request.files['file']
#
#         if file.filename == '':
#             return jsonify({'error': 'No file selected'}), 400
#
#         # Generate unique job name and S3 key
#         job_name = f"transcribe-{uuid.uuid4()}"
#         file_extension = os.path.splitext(file.filename)[1]
#         s3_key = f"audio/{job_name}{file_extension}"
#
#         # Upload file to S3
#         s3_client.upload_fileobj(file, S3_BUCKET, s3_key)
#
#         # Start transcription job
#         file_uri = f"s3://{S3_BUCKET}/{s3_key}"
#
#         transcribe_client.start_transcription_job(
#             TranscriptionJobName=job_name,
#             Media={'MediaFileUri': file_uri},
#             MediaFormat=file_extension.lstrip('.'),
#             LanguageCode=request.form.get('language_code', 'en-US')
#         )
#
#         # Wait for transcription to complete (polling)
#         max_attempts = 60  # Maximum 5 minutes (60 * 5 seconds)
#         attempt = 0
#
#         while attempt < max_attempts:
#             response = transcribe_client.get_transcription_job(
#                 TranscriptionJobName=job_name
#             )
#
#             status = response['TranscriptionJob']['TranscriptionJobStatus']
#
#             if status == 'COMPLETED':
#                 # Get transcript
#                 transcript_uri = response['TranscriptionJob']['Transcript']['TranscriptFileUri']
#
#                 # Fetch transcript from URI
#                 import json
#                 import urllib.request
#
#                 with urllib.request.urlopen(transcript_uri) as url:
#                     transcript_data = json.loads(url.read().decode())
#
#                 transcript_text = transcript_data['results']['transcripts'][0]['transcript']
#
#                 # Clean up: delete S3 file and transcription job
#                 s3_client.delete_object(Bucket=S3_BUCKET, Key=s3_key)
#                 transcribe_client.delete_transcription_job(TranscriptionJobName=job_name)
#
#                 return jsonify({
#                     'success': True,
#                     'transcript': transcript_text
#                 }), 200
#
#             elif status == 'FAILED':
#                 failure_reason = response['TranscriptionJob'].get('FailureReason', 'Unknown error')
#
#                 # Clean up S3 file
#                 s3_client.delete_object(Bucket=S3_BUCKET, Key=s3_key)
#
#                 return jsonify({
#                     'error': f'Transcription failed: {failure_reason}'
#                 }), 500
#
#             # Still in progress, wait before checking again
#             time.sleep(5)
#             attempt += 1
#
#         # Timeout
#         return jsonify({
#             'error': 'Transcription timeout. Job may still be processing.'
#         }), 408
#
#     except Exception as e:
#         return jsonify({'error': str(e)}), 500


@app.route('/summarize-transcript', methods=['POST'])
def summarize_transcript():
    """
    Summarize a transcript using Google Gemini 2.5 Flash.
    Accepts JSON with 'transcript' field or form data with 'transcript'.
    Optional 'custom_prompt' to customize the summarization prompt.
    Optional 'summary_language' to specify output language (zh-HK, zh-CN, en).
    """
    try:
        # Check if Gemini is configured
        if not GOOGLE_API_KEY:
            return jsonify({
                'error': 'Google Gemini API not configured. Please set GOOGLE_API_KEY in environment variables.'
            }), 500

        # Get transcript from request
        if request.is_json:
            data = request.get_json()
            transcript = data.get('transcript')
            custom_prompt = data.get('custom_prompt')
            summary_language = data.get('summary_language', 'en')
        else:
            transcript = request.form.get('transcript')
            custom_prompt = request.form.get('custom_prompt')
            summary_language = request.form.get('summary_language', 'en')

        if not transcript:
            return jsonify({'error': 'No transcript provided'}), 400

        # Get language instruction
        language_name = SUMMARY_LANGUAGE_MAP.get(summary_language, 'English')

        # Build the prompt for Gemini
        if custom_prompt:
            prompt = custom_prompt.replace('{transcript}', transcript)
        else:
            prompt = f"""Please analyze the following transcript and provide a comprehensive summary in {language_name}.

Transcript:
{transcript}

Please provide:
1. **Overall Summary**: A concise overview of the main topic and discussion (2-3 sentences)
2. **Key Points**: List the main points discussed (bullet points)
3. **Action Items**: Any tasks, decisions, or follow-up actions mentioned (if any)
4. **Important Details**: Any specific dates, numbers, names, or technical details mentioned

Format your response in a clear, structured way. Respond entirely in {language_name}."""

        # Use Gemini 2.5 Flash model
        model = genai.GenerativeModel('gemini-2.5-flash')

        # Generate summary
        response = model.generate_content(prompt)

        # Create response with explicit UTF-8 encoding for proper Unicode display
        result = jsonify({
            'success': True,
            'summary': response.text,
            'model': 'gemini-2.5-flash',
            'summary_language': summary_language,
            'transcript_length': len(transcript)
        })
        result.headers['Content-Type'] = 'application/json; charset=utf-8'
        return result, 200

    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/health', methods=['GET'])
def health_check():
    """Health check endpoint"""
    return jsonify({'status': 'healthy'}), 200


# ============================================================================
# WebSocket Real-Time Transcription Endpoints
# ============================================================================

@socketio.on('connect')
def handle_connect():
    """Handle client connection"""
    print(f"Client connected: {request.sid}")
    emit('connected', {'status': 'Connected to transcription server'})


@socketio.on('disconnect')
def handle_disconnect():
    """Handle client disconnection and cleanup"""
    print(f"Client disconnected: {request.sid}")

    # Cleanup session if exists
    if request.sid in active_sessions:
        session = active_sessions[request.sid]

        # Run cleanup in async context
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(session.stop())
        finally:
            loop.close()

        del active_sessions[request.sid]
        print(f"Session cleaned up for: {request.sid}")


@socketio.on('start_transcription')
def handle_start_transcription(data):
    """
    Start a new real-time transcription session

    Expected data format:
    {
        "language_code": "en-US"  # Optional, defaults to en-US
    }
    """
    try:
        language_code = data.get('language_code', 'en-US')

        print(f"Starting transcription for {request.sid} with language: {language_code}")

        # Create new session
        session = TranscriptionSession(request.sid, language_code)
        active_sessions[request.sid] = session

        # Start AWS Transcribe stream
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(session.start())
            emit('transcription_started', {
                'status': 'success',
                'message': 'Transcription session started. Send audio chunks now.',
                'language_code': language_code
            })
        except Exception as e:
            emit('error', {'message': f'Failed to start transcription: {str(e)}'})
            if request.sid in active_sessions:
                del active_sessions[request.sid]
        finally:
            # Don't close the loop - we need it for the session
            pass

    except Exception as e:
        print(f"Error starting transcription: {e}")
        emit('error', {'message': str(e)})


@socketio.on('audio_chunk')
def handle_audio_chunk(data):
    """
    Receive audio chunk from client and forward to AWS Transcribe

    Expected data format:
    {
        "chunk": <base64 encoded audio data or raw bytes>
    }
    """
    try:
        session = active_sessions.get(request.sid)

        if not session:
            emit('error', {'message': 'No active transcription session. Call start_transcription first.'})
            return

        # Extract audio chunk (handle both base64 and raw bytes)
        chunk = data.get('chunk')
        if isinstance(chunk, str):
            # If base64 string, decode it
            import base64
            chunk = base64.b64decode(chunk)

        # Send chunk to AWS Transcribe
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(session.send_audio_chunk(chunk))
        finally:
            loop.close()

    except Exception as e:
        print(f"Error processing audio chunk: {e}")
        emit('error', {'message': f'Failed to process audio chunk: {str(e)}'})


@socketio.on('stop_transcription')
def handle_stop_transcription():
    """Stop the transcription session and save audio to S3"""
    try:
        session = active_sessions.get(request.sid)

        if not session:
            emit('error', {'message': 'No active transcription session'})
            return

        # Stop the stream and save audio to S3
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            # Stop the transcription stream
            loop.run_until_complete(session.stop())

            # Save buffered audio to S3
            s3_url = loop.run_until_complete(session.save_to_s3())
        finally:
            loop.close()

        # Remove session
        del active_sessions[request.sid]

        # Prepare response
        response = {
            'status': 'success',
            'message': 'Transcription session ended'
        }

        # Add audio URL if save was successful (convert to HTTPS)
        if s3_url:
            response['audio_url'] = s3_to_https_url(s3_url)

        emit('transcription_stopped', response)

        print(f"Transcription stopped for: {request.sid}")

    except Exception as e:
        print(f"Error stopping transcription: {e}")
        emit('error', {'message': str(e)})


if __name__ == '__main__':
    # Validate required environment variables (S3_BUCKET_NAME removed for local processing)
    # required_vars = ['AWS_ACCESS_KEY_ID', 'AWS_SECRET_ACCESS_KEY']
    # missing_vars = [var for var in required_vars if not os.getenv(var)]

    # if missing_vars:
    #     print(f"Error: Missing required environment variables: {', '.join(missing_vars)}")
    #     exit(1)

    print("\n" + "=" * 50)
    print("Starting Flask server with WebSocket support")
    print("WebSocket endpoint: ws://localhost:5001/socket.io/")
    print("=" * 50 + "\n")

    # Use socketio.run instead of app.run to enable WebSocket support
    socketio.run(app, host='0.0.0.0', port=5001, debug=True)
