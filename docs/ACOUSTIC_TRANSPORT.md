# ChirpDrop Acoustic Packet Transport Specification

This document details the design, data transformation pipeline, concurrency model, and packet size dynamics of the ChirpDrop Acoustic Packet Transport Layer (`app/communication`).

---

## 1. Architectural Scope & Pipeline

The Acoustic Packet Transport Layer bridges structured binary `Packet` objects (`app.core.packet`) with physical acoustic sound waves processed by `AudioEngine` and modulated via `GgWaveAdapter`.

### Transmission Flow

```text
[ Packet Object ]
       │
       ▼  Packet.to_bytes()
[ Binary Buffer: 8B Header + N Payload ]
       │
       ▼  base64.b64encode()
[ ASCII Base64 String ]
       │
       ▼  GgWaveAdapter.encode()
[ float32 PCM Acoustic Waveform ]
       │
       ▼  AudioEngine.play_waveform()
[ Speaker Transducer Playback ]
```

### Reception Flow

```text
[ Microphone Capture (PortAudio) ]
       │
       ▼  SoundDevice InputStream Callback
[ Bounded PCM Queue ]
       │
       ▼  Background AudioDecoderWorker
[ GgWaveAdapter.decode() ]
       │
       ▼  Inbound Bytes (Base64 ASCII)
[ decode_text_to_packet() ]
       │  ├── Strict Base64 validation
       │  ├── Magic preamble verification (b"CD\x01")
       │  ├── Opcode & sequence number checks
       │  └── CRC-16 checksum verification
       ▼
[ Reconstructed Packet Object ]
       │
       ├──► received_packets (Thread-safe Queue)
       └──► Observer Callbacks (register_packet_callback)
```

---

## 2. Text Codec Pipeline (`app/communication/packet_codec.py`)

Because GGWave’s Cython extension expects string inputs (`str`) and passes UTF-8 text to its C++ DSP core, raw binary frames containing arbitrary byte values (such as preambles with null bytes, sequence numbers, or compressed bytes) cannot be passed directly without risking truncation or encoding exceptions.

### Lossless Base64 Transformation
1. **`encode_packet_to_text(packet: Packet) -> str`**:
   - Calls `packet.to_bytes()` to produce verified binary frames.
   - Encodes via `base64.b64encode(raw).decode("ascii")`.
   - Produces an ASCII-safe text payload guaranteeing zero loss.
2. **`decode_text_to_packet(text_or_bytes: Union[str, bytes]) -> Packet`**:
   - Normalizes input from `bytes` or `str` into ASCII text.
   - Validates Base64 alphabet and padding using `base64.b64decode(validate=True)`.
   - Passes recovered binary bytes to `Packet.from_bytes()`.
   - Validates header structure, opcode range, and recomputes the 16-bit CRC checksum.
   - Rejects any corrupted, truncated, or tampered frames before reaching application logic.

---

## 3. Acoustic Transport Engine (`app/communication/acoustic_transport.py`)

The `AcousticTransport` class coordinates packet dispatch and inbound dispatch:

### Non-Duplicative Audio Architecture
- Operates on a single shared `AudioEngine` instance (injected via constructor or created as default).
- Avoids opening multiple redundant PortAudio streams or competing microphone listeners.

### Observer Pattern & Error Isolation
- Callers subscribe to validated inbound packets via `register_packet_callback(callback)`.
- Inbound dispatch invokes each registered callback inside a guarded `try...except` block, ensuring that an unhandled exception in an observer never crashes the background audio decoding worker.
- Valid packets are simultaneously appended to `received_packets` (`queue.Queue[Packet]`) for pull-based consumption.

---

## 4. Packet Sizing & GGWave Buffer Analysis

During hardware and native module analysis in Task 05, a fundamental acoustic modem constraint was uncovered:

### The 140-Byte Native Single-Chirp Buffer
- In GGWave's C++ core (`ggwave.cpp`), the maximum payload buffer for standard variable-length protocols (Protocols 0 through 8) is hardcoded:
  ```cpp
  #define GGWAVE_MAX_DATA_SIZE 140
  ```
- Any text transmission exceeding **140 characters** is encoded without error, but the receiver truncates the decoded message at exactly 140 characters.
- When a truncated Base64 string is decoded, `Packet.from_bytes()` detects the truncated payload or mismatched CRC-16 checksum and rejects the packet (`CorruptedPacketDataError`).

### Mathematical Relationship
$$\text{Max Base64 Length} \le 140 \implies \text{Max Binary Bytes} = \left\lfloor \frac{140}{4} \right\rfloor \times 3 = 105 \text{ bytes}$$

With an 8-byte protocol header:
$$\text{Max Single-Chirp Payload} = 105 - 8 = 97 \text{ bytes}$$

### Architectural Resolution
1. **Full Protocol Capability**: The binary `Packet` specification remains $8 + 120 = 128$ bytes.
2. **File Transfer Chunking**: The subsequent file transfer engine (Task 06) will segment files into chunks $\le 97$ bytes (e.g. 64 or 96 bytes), ensuring every chunk plus header fits inside the 140-character single-chirp window without truncation or multi-packet frame splitting.

---

## 5. Software Waveform Testing vs. Acoustic Hardware Testing

It is critical to distinguish between the two testing tiers:

1. **Software Waveform Integration Testing (`test_acoustic_transport.py`)**:
   - `GgWaveAdapter.encode()` produces a synthetic `float32` waveform in memory.
   - The waveform bytes are fed directly into `GgWaveAdapter.decode()` in software loopback.
   - Validates that modulation algorithms, FSK carrier tones, Base64 codecs, and CRC-16 checks function with 100% mathematical fidelity.
2. **Physical Acoustic Hardware Testing (`tests/manual_audio_test.py`)**:
   - Audio is emitted from physical laptop speakers into physical air.
   - Sound waves travel through ambient air, reflecting off walls and furniture.
   - Microphone hardware, preamp gain, and Windows audio driver filters (Realtek/AMD echo cancellation) capture the acoustic signal.
   - Genuine laptop-to-laptop transfer requires physical acoustic testing across two separate machines.
