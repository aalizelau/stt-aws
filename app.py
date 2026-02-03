import os
import asyncio
import uuid
import time
import json
import urllib.request
from pathlib import Path
from flask import Flask, request, jsonify, Response, stream_with_context
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


@app.route('/transcribe-batch', methods=['POST'])
def transcribe_audio_batch():
    """
    Batch transcription endpoint using AWS Transcribe with S3.
    Supports multiple audio formats: MP3, MP4, WAV, FLAC, OGG, AMR, WebM.
    Accepts audio file upload and returns transcription text.
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

        # Generate unique job name and S3 key
        job_name = f"transcribe-{uuid.uuid4()}"
        file_extension = os.path.splitext(file.filename)[1].lstrip('.')
        s3_key = f"audio/{job_name}.{file_extension}"

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

                # Clean up: delete S3 file and transcription job
                s3_client.delete_object(Bucket=S3_BUCKET, Key=s3_key)
                transcribe_client.delete_transcription_job(TranscriptionJobName=job_name)

                # Calculate total processing time
                total_time = time.time() - start_time

                return jsonify({
                    'success': True,
                    'transcript': transcript_text,
                    'mode': 'batch',
                    'upload_time_seconds': round(upload_time, 2),
                    'total_processing_time_seconds': round(total_time, 2)
                }), 200

            elif status == 'FAILED':
                failure_reason = response['TranscriptionJob'].get('FailureReason', 'Unknown error')

                # Clean up S3 file
                s3_client.delete_object(Bucket=S3_BUCKET, Key=s3_key)

                return jsonify({
                    'error': f'Transcription failed: {failure_reason}'
                }), 500

            # Still in progress, wait before checking again
            time.sleep(5)
            attempt += 1

        # Timeout - clean up S3 file
        s3_client.delete_object(Bucket=S3_BUCKET, Key=s3_key)

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
        else:
            transcript = request.form.get('transcript')
            custom_prompt = request.form.get('custom_prompt')

        if not transcript:
            return jsonify({'error': 'No transcript provided'}), 400

        # Build the prompt for Gemini
        if custom_prompt:
            prompt = custom_prompt.replace('{transcript}', transcript)
        else:
            prompt = f"""Please analyze the following transcript and provide a comprehensive summary.

Transcript:
{transcript}

Please provide:
1. **Overall Summary**: A concise overview of the main topic and discussion (2-3 sentences)
2. **Key Points**: List the main points discussed (bullet points)
3. **Action Items**: Any tasks, decisions, or follow-up actions mentioned (if any)
4. **Important Details**: Any specific dates, numbers, names, or technical details mentioned

Format your response in a clear, structured way."""

        # Use Gemini 2.5 Flash model
        model = genai.GenerativeModel('gemini-2.5-flash')

        # Generate summary
        response = model.generate_content(prompt)

        return jsonify({
            'success': True,
            'summary': response.text,
            'model': 'gemini-2.5-flash',
            'transcript_length': len(transcript)
        }), 200

    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/transcribe-and-summarize', methods=['POST'])
def transcribe_and_summarize():
    """
    Combined endpoint: Transcribe audio using AWS Transcribe batch mode,
    then summarize using Google Gemini 2.5 Flash.
    Accepts audio file upload and returns both transcript and summary.
    Supports multiple audio formats: MP3, MP4, WAV, FLAC, OGG, AMR, WebM.
    """
    try:
        # Check if both services are configured
        if not S3_BUCKET:
            return jsonify({'error': 'S3_BUCKET_NAME not configured in environment variables'}), 500

        if not GOOGLE_API_KEY:
            return jsonify({
                'error': 'Google Gemini API not configured. Please set GOOGLE_API_KEY in environment variables.'
            }), 500

        # Check if file is present
        if 'file' not in request.files:
            return jsonify({'error': 'No file provided'}), 400

        file = request.files['file']

        if file.filename == '':
            return jsonify({'error': 'No file selected'}), 400

        # Generate unique job name and S3 key
        job_name = f"transcribe-{uuid.uuid4()}"
        file_extension = os.path.splitext(file.filename)[1].lstrip('.')
        s3_key = f"audio/{job_name}.{file_extension}"

        # Validate file format
        supported_formats = ['mp3', 'mp4', 'wav', 'flac', 'ogg', 'amr', 'webm', 'm4a']
        if file_extension.lower() not in supported_formats:
            return jsonify({
                'error': f'Unsupported file format: {file_extension}. Supported formats: {", ".join(supported_formats)}'
            }), 400

        # Upload file to S3
        s3_client.upload_fileobj(file, S3_BUCKET, s3_key)

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

                # Clean up: delete S3 file and transcription job
                s3_client.delete_object(Bucket=S3_BUCKET, Key=s3_key)
                transcribe_client.delete_transcription_job(TranscriptionJobName=job_name)

                # Now summarize the transcript using Gemini
                custom_prompt = request.form.get('custom_prompt')

                if custom_prompt:
                    prompt = custom_prompt.replace('{transcript}', transcript_text)
                else:
                    prompt = f"""Please analyze the following transcript and provide a comprehensive summary.

Transcript:
{transcript_text}

Please provide:
1. **Overall Summary**: A concise overview of the main topic and discussion (2-3 sentences)
2. **Key Points**: List the main points discussed (bullet points)
3. **Action Items**: Any tasks, decisions, or follow-up actions mentioned (if any)
4. **Important Details**: Any specific dates, numbers, names, or technical details mentioned

Format your response in a clear, structured way."""

                # Use Gemini 2.5 Flash model
                model = genai.GenerativeModel('gemini-2.0-flash-exp')

                # Generate summary
                gemini_response = model.generate_content(prompt)

                return jsonify({
                    'success': True,
                    'transcript': transcript_text,
                    'summary': gemini_response.text,
                    'mode': 'batch',
                    'model': 'gemini-2.0-flash-exp',
                    'transcript_length': len(transcript_text)
                }), 200

            elif status == 'FAILED':
                failure_reason = response['TranscriptionJob'].get('FailureReason', 'Unknown error')

                # Clean up S3 file
                s3_client.delete_object(Bucket=S3_BUCKET, Key=s3_key)

                return jsonify({
                    'error': f'Transcription failed: {failure_reason}'
                }), 500

            # Still in progress, wait before checking again
            time.sleep(5)
            attempt += 1

        # Timeout - clean up S3 file
        s3_client.delete_object(Bucket=S3_BUCKET, Key=s3_key)

        return jsonify({
            'error': 'Transcription timeout. Job may still be processing.'
        }), 408

    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/health', methods=['GET'])
def health_check():
    """Health check endpoint"""
    return jsonify({'status': 'healthy'}), 200


if __name__ == '__main__':
    # Validate required environment variables (S3_BUCKET_NAME removed for local processing)
    # required_vars = ['AWS_ACCESS_KEY_ID', 'AWS_SECRET_ACCESS_KEY']
    # missing_vars = [var for var in required_vars if not os.getenv(var)]

    # if missing_vars:
    #     print(f"Error: Missing required environment variables: {', '.join(missing_vars)}")
    #     exit(1)

    app.run(host='0.0.0.0', port=5001, debug=True)
