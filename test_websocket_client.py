#!/usr/bin/env python3
"""
Test client for WebSocket real-time transcription

This script demonstrates how to use the WebSocket endpoint for real-time
audio streaming transcription. It reads a PCM audio file and streams it
in chunks to simulate real-time recording.

Usage:
    python test_websocket_client.py <path_to_pcm_file>

Audio format requirements:
    - Format: PCM (raw audio, no headers)
    - Sample rate: 16000 Hz
    - Channels: Mono (1)
    - Bit depth: 16-bit
"""

import socketio
import base64
import time
import sys
import os

# Create Socket.IO client
sio = socketio.Client()

@sio.on('connected')
def on_connected(data):
    print(f"✓ Connected: {data}")

@sio.on('transcription_started')
def on_started(data):
    print(f"✓ Transcription started: {data}")
    print("=" * 60)
    print("Streaming audio chunks...")
    print("=" * 60)

@sio.on('transcription_result')
def on_result(data):
    """Receive and display real-time transcription results"""
    text = data.get('text', '')
    is_partial = data.get('is_partial', False)

    # Use different markers for partial vs final results
    marker = "🔄" if is_partial else "✓"
    result_type = "PARTIAL" if is_partial else "FINAL"

    print(f"\n{marker} [{result_type}] {text}")

@sio.on('transcription_stopped')
def on_stopped(data):
    print("\n" + "=" * 60)
    print(f"✓ Transcription stopped: {data}")
    print("=" * 60)

@sio.on('error')
def on_error(data):
    print(f"❌ Error: {data}")

@sio.on('disconnect')
def on_disconnect():
    print("Disconnected from server")

def stream_audio_file(file_path, chunk_size=3200, delay=0.1):
    """
    Stream audio file in chunks to simulate real-time recording

    Args:
        file_path: Path to PCM audio file
        chunk_size: Size of each chunk in bytes (default: 3200 = ~100ms at 16kHz)
        delay: Delay between chunks in seconds (default: 0.1 = 100ms)
    """
    if not os.path.exists(file_path):
        print(f"❌ Error: File not found: {file_path}")
        return

    file_size = os.path.getsize(file_path)
    print(f"\nFile: {file_path}")
    print(f"Size: {file_size:,} bytes ({file_size / (16000 * 2):.2f} seconds of audio)")
    print(f"Chunk size: {chunk_size} bytes (~{chunk_size / (16000 * 2) * 1000:.0f}ms)")
    print(f"Delay between chunks: {delay * 1000:.0f}ms\n")

    chunks_sent = 0
    bytes_sent = 0

    try:
        with open(file_path, 'rb') as f:
            while True:
                chunk = f.read(chunk_size)
                if not chunk:
                    break

                # Encode to base64 and send
                base64_chunk = base64.b64encode(chunk).decode('utf-8')
                sio.emit('audio_chunk', {'chunk': base64_chunk})

                chunks_sent += 1
                bytes_sent += len(chunk)

                # Progress indicator
                progress = (bytes_sent / file_size) * 100
                print(f"\rProgress: {progress:.1f}% ({chunks_sent} chunks, {bytes_sent:,}/{file_size:,} bytes)", end='', flush=True)

                # Simulate real-time streaming delay
                time.sleep(delay)

        print(f"\n\n✓ Finished streaming {chunks_sent} chunks ({bytes_sent:,} bytes)")

    except Exception as e:
        print(f"\n❌ Error streaming file: {e}")

def main():
    """Main function"""
    if len(sys.argv) < 2:
        print("Usage: python test_websocket_client.py <path_to_pcm_file> [language_code]")
        print("\nExample:")
        print("  python test_websocket_client.py audio.pcm en-US")
        print("\nNote: Audio file must be PCM format, 16kHz, mono, 16-bit")
        sys.exit(1)

    audio_file = sys.argv[1]
    language_code = sys.argv[2] if len(sys.argv) > 2 else 'en-US'

    server_url = 'http://localhost:5001'

    print("=" * 60)
    print("WebSocket Real-Time Transcription Test Client")
    print("=" * 60)
    print(f"Server: {server_url}")
    print(f"Language: {language_code}")
    print("=" * 60)

    try:
        # Connect to server
        print("\nConnecting to server...")
        sio.connect(server_url)

        # Wait a bit for connection to establish
        time.sleep(0.5)

        # Start transcription session
        print(f"Starting transcription session (language: {language_code})...")
        sio.emit('start_transcription', {'language_code': language_code})

        # Wait for session to be ready
        time.sleep(1)

        # Stream the audio file
        stream_audio_file(audio_file)

        # Wait a bit for final results
        print("\nWaiting for final results...")
        time.sleep(2)

        # Stop transcription
        print("\nStopping transcription...")
        sio.emit('stop_transcription')

        # Wait for stop confirmation
        time.sleep(1)

        # Disconnect
        print("\nDisconnecting...")
        sio.disconnect()

        print("\n✓ Test completed successfully!\n")

    except Exception as e:
        print(f"\n❌ Error: {e}")
        sys.exit(1)

if __name__ == '__main__':
    main()
