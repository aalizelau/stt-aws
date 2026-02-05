# WebSocket Real-Time Streaming Implementation

## Overview

This document explains the WebSocket-based real-time audio streaming implementation for mobile apps. This feature enables **true real-time transcription** where audio chunks are sent to the server as the user is recording, without waiting for the complete file upload.

## Architecture

### High-Level Flow

```
Mobile App (Recording) ──> WebSocket ──> Backend ──> AWS Transcribe Streaming API
                                                              │
Mobile App (Display)   <── WebSocket <── Backend <───────────┘
```

### Key Components

1. **WebSocket Server** (Flask-SocketIO)
   - Handles bidirectional communication
   - Manages multiple concurrent sessions
   - Routes audio chunks to AWS Transcribe
   - Streams results back to clients

2. **Session Management** (`TranscriptionSession`)
   - One session per connected client
   - Maintains AWS Transcribe stream connection
   - Handles lifecycle (start → process → stop)

3. **Event Handlers**
   - `RealtimeEventHandler`: Receives results from AWS, emits to WebSocket clients
   - Connection lifecycle handlers: connect, disconnect, cleanup

4. **AWS Transcribe Streaming API**
   - Processes audio chunks in real-time
   - Returns partial and final results
   - Supports multiple languages

## Data Flow

### Session Lifecycle

```
1. Client connects
   └─> Server: "connected" event

2. Client: emit("start_transcription", {language_code})
   ├─> Server: Create session
   ├─> Server: Initialize AWS Transcribe stream
   └─> Client: "transcription_started" event

3. Client: emit("audio_chunk", {chunk}) [repeated]
   ├─> Server: Forward to AWS Transcribe
   ├─> AWS: Process and return results
   └─> Client: "transcription_result" event {text, is_partial}

4. Client: emit("stop_transcription")
   ├─> Server: Close AWS stream
   ├─> Server: Cleanup session
   └─> Client: "transcription_stopped" event

5. Client disconnects
   └─> Server: Automatic cleanup
```

## WebSocket Events

### Client → Server

| Event | Data | Description |
|-------|------|-------------|
| `start_transcription` | `{language_code: 'en-US'}` | Initialize transcription session |
| `audio_chunk` | `{chunk: base64_encoded_pcm}` | Send audio chunk (100-200ms) |
| `stop_transcription` | (none) | End session gracefully |

### Server → Client

| Event | Data | Description |
|-------|------|-------------|
| `connected` | `{status: 'Connected...'}` | Connection established |
| `transcription_started` | `{status, message, language_code}` | Session ready, start sending audio |
| `transcription_result` | `{text: '...', is_partial: true/false}` | Real-time transcription result |
| `transcription_stopped` | `{status, message}` | Session ended |
| `error` | `{message: '...'}` | Error occurred |

## Audio Format Requirements

### Critical Specifications

- **Format**: PCM (raw, uncompressed audio)
- **Sample Rate**: 16000 Hz (16 kHz)
- **Channels**: Mono (1 channel)
- **Bit Depth**: 16-bit signed integer
- **Byte Order**: Little-endian
- **Chunk Size**: 3200-6400 bytes (100-200ms of audio)

### Why These Requirements?

1. **PCM Format**: AWS Transcribe Streaming API only accepts PCM
2. **16 kHz Sample Rate**: Optimal for speech recognition (8kHz too low, 48kHz overkill)
3. **Mono**: Speech doesn't need stereo, reduces bandwidth by 50%
4. **16-bit**: Good quality without excessive data
5. **100-200ms chunks**: Balance between latency and network efficiency

### Calculating Chunk Size

```
Sample Rate: 16000 Hz
Bit Depth: 16-bit = 2 bytes
Channels: 1 (mono)

Data rate = 16000 samples/sec × 2 bytes × 1 channel = 32000 bytes/sec

For 100ms chunks:
32000 bytes/sec × 0.1 sec = 3200 bytes

For 200ms chunks:
32000 bytes/sec × 0.2 sec = 6400 bytes
```

## Implementation Details

### Backend (Python)

#### Session Management

```python
class TranscriptionSession:
    - session_id: Unique identifier (Socket.IO sid)
    - language_code: Language for transcription
    - client: TranscribeStreamingClient
    - stream: Active AWS stream
    - handler: Event handler for results
    - is_active: Session state flag
```

#### Event Handler

```python
class RealtimeEventHandler(TranscriptResultStreamHandler):
    async def handle_transcript_event(self, transcript_event):
        # Receive from AWS Transcribe
        # Emit to WebSocket client using socketio.emit()
```

#### Async/Sync Bridge

Flask-SocketIO uses synchronous event handlers, but AWS Transcribe SDK is async. We bridge this gap:

```python
@socketio.on('audio_chunk')
def handle_audio_chunk(data):
    # Create new event loop
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        # Run async operation
        loop.run_until_complete(session.send_audio_chunk(chunk))
    finally:
        loop.close()
```

### Mobile Implementation

#### iOS (Swift)

**Key Components:**
- `SocketManager` + `SocketIOClient`: WebSocket connection
- `AVAudioEngine`: Audio capture at 16kHz PCM
- `installTap()`: Captures audio buffers in real-time
- Base64 encoding: Convert audio data for JSON transmission

**Audio Capture:**
```swift
let recordingFormat = AVAudioFormat(
    commonFormat: .pcmFormatInt16,  // 16-bit PCM
    sampleRate: 16000,              // 16kHz
    channels: 1,                    // Mono
    interleaved: true
)

inputNode.installTap(onBus: 0, bufferSize: 1600, format: recordingFormat) { buffer, time in
    // Convert buffer to Data
    let audioData = audioBufferToData(buffer: buffer)

    // Send via WebSocket
    socket.emit("audio_chunk", ["chunk": audioData.base64EncodedString()])
}
```

#### Android (Kotlin)

**Key Components:**
- `Socket`: WebSocket connection (Socket.IO)
- `AudioRecord`: Low-level audio capture
- Coroutines: Asynchronous audio streaming
- Base64 encoding: Convert audio for JSON

**Audio Capture:**
```kotlin
val audioRecord = AudioRecord(
    MediaRecorder.AudioSource.MIC,
    16000,                          // Sample rate
    AudioFormat.CHANNEL_IN_MONO,    // Mono
    AudioFormat.ENCODING_PCM_16BIT, // 16-bit PCM
    bufferSize
)

scope.launch {
    val buffer = ShortArray(1600)  // ~100ms
    while (isRecording) {
        val read = audioRecord.read(buffer, 0, buffer.size)
        // Convert to bytes and send
    }
}
```

## Comparison with Other Modes

| Feature | WebSocket Streaming | HTTP SSE Streaming | Batch Mode |
|---------|-------------------|-------------------|------------|
| **Upload Method** | Chunks while recording | Complete file first | Complete file to S3 |
| **Latency** | Lowest (~100-300ms) | Medium (file upload + processing) | Highest (upload + queue + process) |
| **S3 Required** | No | No | Yes |
| **Audio Format** | PCM only | PCM only | Multiple formats |
| **Use Case** | Mobile apps, live recording | File transcription with progress | Batch processing, MP3/MP4 files |
| **Bi-directional** | Yes | No (one-way SSE) | No |
| **Complexity** | Highest | Medium | Lowest |

## Performance Considerations

### Bandwidth Usage

PCM 16kHz mono 16-bit:
- Data rate: 32 KB/s (256 kbps)
- Per minute: ~1.92 MB
- Per hour: ~115 MB

**Note**: This is relatively high compared to compressed formats. Consider using Opus codec with transcoding if bandwidth is a concern.

### Latency Breakdown

Total latency = Network + Processing + Buffering

1. **Network latency**:
   - WebSocket: 20-100ms (depends on connection)
   - Upload chunk: 50-150ms (depends on chunk size & network)

2. **AWS Processing**:
   - Transcribe API: 100-500ms

3. **Buffering**:
   - Client buffer: 100-200ms (chunk size)
   - Server buffer: minimal

**Total**: Typically 200-800ms from speech to displayed text

### Scalability

**Current implementation** (in-memory sessions):
- Good for: Development, small deployments (<100 concurrent users)
- Limitation: Sessions lost on server restart

**Production recommendations**:
1. Use Redis for session storage
2. Implement horizontal scaling with sticky sessions
3. Add WebSocket load balancer (e.g., Socket.IO with Redis adapter)
4. Monitor AWS Transcribe quotas and costs

## Error Handling

### Connection Issues

1. **Client disconnects unexpectedly**:
   - `disconnect` handler automatically cleans up session
   - AWS stream is closed
   - Resources are freed

2. **Network interruption**:
   - Client should implement reconnection logic
   - Session must be restarted after reconnection

3. **AWS Transcribe errors**:
   - Emitted to client via `error` event
   - Client should display error and allow retry

### Audio Quality Issues

1. **Wrong format**:
   - AWS will reject non-PCM audio
   - Error emitted to client

2. **Wrong sample rate**:
   - Transcription quality degrades
   - Results may be garbled

3. **Chunk too large/small**:
   - Too large: Increased latency
   - Too small: Network overhead, possible packet loss

## Security Considerations

### Authentication

Current implementation has no authentication. For production:

```python
@socketio.on('connect')
def handle_connect(auth):
    # Verify JWT token or API key
    if not verify_token(auth.get('token')):
        return False  # Reject connection
```

### CORS

Currently allows all origins (`cors_allowed_origins="*"`). For production:

```python
socketio = SocketIO(app, cors_allowed_origins=["https://yourdomain.com"])
```

### Rate Limiting

Implement rate limiting to prevent abuse:
- Max connections per IP
- Max audio duration per session
- Max concurrent sessions per user

### Data Privacy

- Audio is streamed but not stored (unless explicitly saved)
- Transcripts are returned but not logged (unless explicitly logged)
- AWS Transcribe may retain data per AWS policies
- Consider encryption for sensitive audio (TLS/SSL)

## Testing

### Test Client

Use the provided test client:

```bash
# Install dependencies
pip install python-socketio

# Run test (requires PCM audio file)
python test_websocket_client.py audio.pcm en-US
```

### Creating Test PCM Audio

Convert an existing audio file to PCM:

```bash
# Using ffmpeg
ffmpeg -i input.mp3 -ar 16000 -ac 1 -f s16le -acodec pcm_s16le output.pcm

# Using sox
sox input.mp3 -r 16000 -c 1 -b 16 -e signed-integer output.pcm
```

### Manual Testing with Socket.IO Client

```javascript
// Browser console
const socket = io('http://localhost:5001');
socket.on('connected', console.log);
socket.on('transcription_result', console.log);
socket.emit('start_transcription', {language_code: 'en-US'});
```

## Troubleshooting

### Common Issues

1. **"Cannot import flask_socketio"**
   - Solution: `pip install flask-socketio python-socketio eventlet`

2. **No audio captured on mobile**
   - iOS: Check microphone permissions in Info.plist
   - Android: Check RECORD_AUDIO permission granted

3. **Garbled transcription**
   - Check audio format (must be 16kHz PCM mono 16-bit)
   - Verify sample rate conversion is correct

4. **High latency**
   - Reduce chunk size (but not below 1600 bytes)
   - Check network connection
   - Verify server location (closer to client = lower latency)

5. **Connection drops**
   - Implement reconnection logic in client
   - Check firewall/proxy WebSocket support
   - Verify Socket.IO version compatibility

## Future Improvements

1. **Audio Compression**
   - Add Opus codec support
   - Transcode on server to reduce bandwidth

2. **Session Persistence**
   - Store sessions in Redis
   - Resume on reconnection

3. **Multiple Language Detection**
   - Auto-detect language from audio
   - Switch languages mid-stream

4. **Speaker Diarization**
   - Identify different speakers
   - Requires custom AWS Transcribe configuration

5. **Real-time Translation**
   - Combine with translation API
   - Stream translated text alongside transcription

## Resources

- [AWS Transcribe Streaming API Docs](https://docs.aws.amazon.com/transcribe/latest/dg/streaming.html)
- [Flask-SocketIO Documentation](https://flask-socketio.readthedocs.io/)
- [Socket.IO Protocol](https://socket.io/docs/v4/)
- [iOS AVAudioEngine Guide](https://developer.apple.com/documentation/avfaudio/avaudioengine)
- [Android AudioRecord Guide](https://developer.android.com/reference/android/media/AudioRecord)
