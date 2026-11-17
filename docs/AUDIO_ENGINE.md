# ChirpDrop Audio Engine Architecture & Subsystem Specification

This document details the real-time audio subsystem, device management, GGWave modem integration, and acoustic echo suppression architecture of ChirpDrop.

---

## 1. Architectural Overview

The audio engine (`app/audio`) bridges hardware acoustic transducers (speakers and microphones) with digital modulation/demodulation routines.

```text
  +------------------+         +--------------------+         +-------------------+
  | SoundDevice (Mic)| ------> | Real-Time Callback | ------> | Bounded PCM Queue |
  +------------------+         +--------------------+         +-------------------+
                                         |                              |
                             (Echo Suppression Check)                   v
                                                             +---------------------+
                                                             |  Background Worker  |
                                                             +---------------------+
                                                                        |
                                                                        v
                                                             +---------------------+
                                                             |   GGWave Decoder    |
                                                             +---------------------+
                                                                        |
                                                                        v
                                                             +---------------------+
                                                             | Dispatch Callbacks  |
                                                             +---------------------+

  +------------------+         +--------------------+         +-------------------+
  |  SoundDevice     | <------ | Speaker Playback   | <------ | GgWaveAdapter     |
  |  (Speaker Output)|         | (Marks Tx State)   |         | (encode payload)  |
  +------------------+         +--------------------+         +-------------------+
```

### Decoupled Concurrency Pipeline
1. **Audio Hardware Thread**: PortAudio runs high-priority OS audio threads. The input callback `_audio_callback()` executes with strict real-time deadlines: it copies incoming float32 sample blocks and posts them to a bounded FIFO queue (`_audio_queue`) without blocking.
2. **Background Demodulation Thread**: A dedicated worker thread (`ChirpDrop-AudioDecoderWorker`) continuously consumes PCM chunks from the queue, executes GGWave demodulation, and pushes decoded frames to observer callbacks and `received_queue`.
3. **Playback Thread**: Audio transmissions are played through `sounddevice.play()`. The transmission state machine tracks active playback and enforces post-transmission guard delays.

---

## 2. GGWave API Findings & Integration Analysis

During environment probing of `ggwave-wheels==0.4.2.5` on Windows 11 x64, the following native behaviors were established:

| API Property | Native Finding | Engineering Adaptation |
| :--- | :--- | :--- |
| **Available Functions** | `init()`, `free()`, `encode()`, `decode()`, `getDefaultParameters()`, `rxToggleProtocol()`, `txToggleProtocol()`, `disableLog()`, `enableLog()` | All wrapped safely inside `GgWaveAdapter`. |
| **Sample Rate** | 48,000 Hz (`48000.0` default in `getDefaultParameters()`) | Configured globally as standard across all components. |
| **PCM Data Type** | **32-bit floating-point (`float32`) mono**, 4 bytes per sample | Streams and buffers are strictly formatted as `float32`. |
| **Chunking Behavior** | GGWave expects frames of 1024 samples (4,096 bytes per block). Decodes incrementally across sequential chunks. | Audio stream block size is set to 1,024 frames. |
| **`encode()` Signature** | `encode(payload: str, protocolId=1, volume=10, instance=None)` | Expects `str`. UTF-8 conversion is enforced. Base64 is used when sending arbitrary binary bytes. |
| **`decode()` Signature** | `decode(instance: int, waveform: bytes) -> bytes` | Decoded payload is returned as raw bytes. Returns `None` if incomplete. |
| **Protocol IDs** | Protocols `0` to `8` verified operational (see table below). | Mapped directly to Audible and Ultrasonic configurations. |
| **Native Logging** | `ggwave.disableLog()` silences verbose stdout logging from C++ core. | Called upon adapter module initialization. |

### Verified Modulation Protocols

| Protocol ID | Mode Name | Operating Band | FFT Frequency Range | Primary Purpose |
| :--- | :--- | :--- | :--- | :--- |
| **`0`** | Audible Normal | Audible | 1.8 kHz – 6.0 kHz | High robustness across all hardware |
| **`1`** | Audible Fast | Audible | 1.8 kHz – 6.0 kHz | Higher throughput audible transmission |
| **`2`** | Audible Fastest | Audible | 1.8 kHz – 6.0 kHz | Maximum throughput audible mode |
| **`3`** | Ultrasonic Normal | Near-Ultrasound | 15.0 kHz – 19.1 kHz | Human-inaudible transmission |
| **`4`** | Ultrasonic Fast | Near-Ultrasound | 15.0 kHz – 19.1 kHz | Fast near-ultrasonic transmission |
| **`5`** | Ultrasonic Fastest | Near-Ultrasound | 15.0 kHz – 19.1 kHz | Maximum throughput near-ultrasound |
| **`6 – 8`** | Dual-Tone Profiles | Dual Audible | Multi-carrier | Dual-tone audible modes |

---

## 3. Audio Device Management (`app/audio/device_manager.py`)

The `AudioDeviceManager` class interfaces with Windows audio endpoints:

- **Endpoint Segregation**: Filters devices by input channels (microphones) and output channels (speakers/headphones).
- **Default Resolution**: Identifies OS default input and output devices.
- **Capability Validation**: Uses `sd.check_input_settings` and `sd.check_output_settings` to verify whether a device natively accepts 48 kHz mono float32 streams.
- **Graceful Error Handling**: Raises `DeviceNotFoundError` and `DeviceConfigurationError` with descriptive diagnostics when hardware is absent or incompatible.

---

## 4. Real-Time Audio Engine (`app/audio/audio_engine.py`)

### Buffer & Queue Management
- **Block Size**: 1,024 frames (4,096 bytes per float32 block at 48 kHz).
- **Queue Capacity**: Bounded at 150 blocks (~3.2 seconds of buffer memory).
- **Overflow Handling**: If the queue reaches capacity, incoming blocks are dropped safely, and `dropped_blocks_count` increments without throwing exceptions or crashing the PortAudio callback.

### Echo Suppression & Transmission State Machine
To avoid speaker-to-microphone feedback loops:
1. When local playback starts:
   - Sets `_is_transmitting = True`.
   - Clears `_tx_finished_time = 0.0`.
2. Real-time audio callback checks `is_suppressed()`:
   - While `_is_transmitting == True`, all microphone blocks are discarded immediately.
3. When local playback completes:
   - Sets `_is_transmitting = False`.
   - Records `_tx_finished_time = time.monotonic()`.
4. Post-transmission guard delay:
   - During the 250 ms guard window (`POST_TRANSMISSION_GUARD_MS`), `is_suppressed()` continues to return `True` to allow room reverberation and internal speaker decay to dissipate before the microphone resumes demodulation.

---

## 5. Manual Hardware Test Utility (`tests/manual_audio_test.py`)

An interactive script to evaluate acoustic transmission on physical hardware:

```powershell
.\.venv\Scripts\python.exe tests/manual_audio_test.py --mode audible --volume 25
```

### Safety Features
- **No Automatic Playback**: Requires explicit interactive confirmation (`[y/N]`) before emitting any sound.
- **Conservative Volume**: Defaults to 25% gain to prevent ear fatigue or speaker distortion.
- **Bounded Duration**: Listens for a fixed duration (default: 6 seconds) before automatically releasing audio devices.
- **Clean Signal Handling**: Gracefully stops streams on `Ctrl+C`.

---

## 6. Known Environmental & Acoustic Limitations

1. **Laptop Echo Cancellation & Noise Suppression**:
   - Modern Windows laptop audio drivers (Realtek Audio Enhancements, Waves MaxxAudio, AMD/Intel Smart Sound) often apply aggressive digital noise cancellation and speaker-echo cancellation.
   - During single-laptop self-reception tests, these driver-level filters may cancel out the speaker sound before it reaches the microphone. Testing between two separate physical laptops is the intended operating model.
2. **High-Frequency Transducer Attenuation**:
   - Near-ultrasonic frequencies (15–19 kHz) undergo greater atmospheric absorption and steep roll-off on budget laptop speakers and electret microphones. Ultrasonic mode requires proximity (< 1.5 m) and higher volume.
