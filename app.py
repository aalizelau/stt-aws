import os
import asyncio
import uuid
import time
import json
import urllib.request
from pathlib import Path
from flask import Flask, request, jsonify
from amazon_transcribe.client import TranscribeStreamingClient
from amazon_transcribe.handlers import TranscriptResultStreamHandler
from amazon_transcribe.model import TranscriptEvent
from dotenv import load_dotenv

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

                return jsonify({
                    'success': True,
                    'transcript': transcript_text,
                    'mode': 'batch'
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
