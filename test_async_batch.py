#!/usr/bin/env python3
"""
Test script for async batch transcription endpoints.

This demonstrates the async workflow:
1. Start a transcription job (returns immediately)
2. Poll for status
3. Retrieve results when complete
"""

import requests
import time
import sys


def test_async_batch_transcription(audio_file_path, language_code='en-US', base_url='http://44.223.62.169:5001'):
    """Test async batch transcription workflow"""

    print("=" * 60)
    print("ASYNC BATCH TRANSCRIPTION TEST")
    print("=" * 60)

    # Step 1: Start transcription job
    print(f"\n1. Starting transcription job for: {audio_file_path}")
    print("-" * 60)

    with open(audio_file_path, 'rb') as audio_file:
        files = {'file': audio_file}
        data = {'language_code': language_code}

        response = requests.post(
            f'{base_url}/transcribe-batch-async',
            files=files,
            data=data
        )

    if response.status_code != 201:
        print(f"❌ Failed to start job: {response.json()}")
        return

    result = response.json()
    job_name = result['job_name']

    print(f"✅ Job started successfully!")
    print(f"   Job Name: {job_name}")
    print(f"   Status: {result['status']}")
    print(f"   S3 URL: {result['s3_url']}")
    print(f"   Upload Time: {result['upload_time_seconds']}s")
    print(f"   Check status at: {base_url}{result['status_endpoint']}")

    # Step 2: Poll for status
    print(f"\n2. Polling for job completion...")
    print("-" * 60)

    max_attempts = 60  # 5 minutes max
    poll_interval = 5  # seconds

    for attempt in range(1, max_attempts + 1):
        # Check status
        status_response = requests.get(f'{base_url}/transcribe-job/{job_name}')

        if status_response.status_code != 200:
            print(f"❌ Failed to get status: {status_response.json()}")
            return

        status_result = status_response.json()
        status = status_result['status']

        print(f"   Attempt {attempt}: Status = {status}")

        if status == 'COMPLETED':
            print(f"\n✅ Transcription completed!")
            print("=" * 60)
            print("RESULTS")
            print("=" * 60)
            print(f"\nJob Name: {status_result['job_name']}")
            print(f"Language: {status_result['language_code']}")
            print(f"Creation Time: {status_result['creation_time']}")
            print(f"Completion Time: {status_result['completion_time']}")
            print(f"Media Format: {status_result['media_format']}")
            print(f"Sample Rate: {status_result['media_sample_rate_hz']} Hz")
            print(f"\nTranscript:")
            print("-" * 60)
            print(status_result['transcript'])
            print("-" * 60)
            return status_result

        elif status == 'FAILED':
            print(f"\n❌ Transcription failed!")
            print(f"   Failure Reason: {status_result.get('failure_reason', 'Unknown')}")
            return None

        elif status == 'IN_PROGRESS':
            # Wait before next poll
            if attempt < max_attempts:
                print(f"   Waiting {poll_interval}s before next check...")
                time.sleep(poll_interval)

        else:
            print(f"   Unexpected status: {status}")
            time.sleep(poll_interval)

    print(f"\n⚠️  Timeout after {max_attempts * poll_interval}s. Job may still be processing.")
    print(f"   Check manually at: {base_url}/transcribe-job/{job_name}")


def test_list_jobs(base_url='http://44.223.62.169:5001'):
    """Test listing transcription jobs"""

    print("\n" + "=" * 60)
    print("LIST JOBS TEST")
    print("=" * 60)

    response = requests.get(f'{base_url}/transcribe-jobs')

    if response.status_code != 200:
        print(f"❌ Failed to list jobs: {response.json()}")
        return

    result = response.json()

    print(f"\nFound {result['count']} jobs")
    print(f"Filters: {result['filters']}")
    print("-" * 60)

    for i, job in enumerate(result['jobs'], 1):
        print(f"\n{i}. {job['job_name']}")
        print(f"   Status: {job['status']}")
        print(f"   Language: {job['language_code']}")
        print(f"   Created: {job['creation_time']}")
        if job.get('completion_time'):
            print(f"   Completed: {job['completion_time']}")
        if job.get('failure_reason'):
            print(f"   ❌ Failed: {job['failure_reason']}")


def main():
    if len(sys.argv) < 2:
        print("Usage: python test_async_batch.py <audio_file> [language_code]")
        print("\nExamples:")
        print("  python test_async_batch.py audio.mp3")
        print("  python test_async_batch.py audio.mp3 en-US")
        print("  python test_async_batch.py audio.mp3 zh-CN")
        sys.exit(1)

    audio_file = sys.argv[1]
    language_code = sys.argv[2] if len(sys.argv) > 2 else 'en-US'

    # Test async batch transcription
    test_async_batch_transcription(audio_file, language_code)

    # Test listing jobs
    test_list_jobs()


if __name__ == '__main__':
    main()
