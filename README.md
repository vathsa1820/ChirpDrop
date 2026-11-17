# ChirpDrop 📡🔊

**Air-Gapped Acoustic Data and File Transfer Application for Windows**

ChirpDrop is an offline, air-gapped communication and file exchange system designed for Windows 10 and 11 workstations. It enables two physically isolated computers to exchange structured binary messages and files using only their built-in speakers and microphones—eliminating any reliance on network interfaces, radio frequencies, or physical media.

---

## 1. Executive Summary & Use Case

In high-security, sensitive, or industrial environments, air-gapped workstations are isolated from local and wide area networks to prevent remote exploitation and unauthorized data exfiltration. However, transmitting small operational payloads, firmware manifests, configuration tokens, or short text messages between adjacent air-gapped systems often requires physical USB flash drives, which present substantial supply chain and Stuxnet-style malware infection risks.

**ChirpDrop eliminates physical and radio attack vectors:**
- **Zero RF Interfaces**: Operates without Wi-Fi, Bluetooth, Cellular, NFC, or SDR hardware.
- **Zero Network Infrastructure**: Requires no Ethernet, IP routing, or local DHCP/DNS.
- **Zero Removable Media**: Completely eliminates USB thumb drives and optical media.
- **Physical Proximity Assurance**: Sound-wave propagation enforces strict line-of-sight/room-bound proximity.

---

## 2. Key Capabilities

1. **Bidirectional Acoustic Messaging**: Near-real-time text conversation over acoustic carrier waves.
2. **Chunked Binary File Transfer**: Reliable segmentation of arbitrary files into verified frames.
3. **In-Flight Compression**: Transparent Zlib compression prior to packetization to minimize transmission time.
4. **Sliding Window Flow Control**: Transmit window of 4 packets with selective retransmission of dropped frames.
5. **CRC & Cryptographic Integrity**:
   - Per-packet 16-bit CRC checksum validation.
   - End-to-end SHA-256 cryptographic digest verification on reconstructed files.
6. **Dual Acoustic Profiles**:
   - **Audible Mode (1.5 kHz – 15 kHz)**: Maximizes acoustic resilience across low-cost laptop speakers and noisy ambient conditions.
   - **Ultrasonic Mode (15 kHz – 20 kHz)**: Near-inaudible acoustic transfer for quiet office environments.
7. **Feedback Suppression**:
   - Half-duplex turn-taking and mandatory post-transmission guard delay (250 ms) to prevent speaker-to-microphone loopback self-reception.
8. **Decoupled Architecture**: Audio streaming, packet framing, transfer state machines, and the PySide6 UI run on dedicated background threads communicating via thread-safe queues.

---

## 3. Physical & Acoustic Transport Protocol

ChirpDrop employs a framed binary packet protocol engineered specifically for noisy, band-limited, reverberant acoustic channels.

### Binary Frame Layout (Maximum 128 Bytes)

```
 0                   1                   2                   3
 0 1 2 3 4 5 6 7 8 9 0 1 2 3 4 5 6 7 8 9 0 1 2 3 4 5 6 7 8 9 0 1
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
|       Magic Preamble ('C', 'D', 0x01)         |    Opcode     |
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
|        Sequence Number        |      CRC-16 Checksum          |
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
|                                                               |
|                  Payload (0 to 120 Bytes)                     |
|                                                               |
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
```

### Protocol Fields

| Field | Size | Type | Description |
| :--- | :--- | :--- | :--- |
| **Magic Preamble** | 3 Bytes | `b"CD\x01"` | Fixed marker identifying genuine ChirpDrop frames amidst background noise. |
| **Opcode** | 1 Byte | `uint8` | Frame intent (`0x01`: SYN, `0x02`: DATA, `0x03`: NACK, `0x04`: FIN). |
| **Sequence Number**| 2 Bytes | `uint16` (BE) | Monotonically increasing chunk index (0 to 65535). |
| **Checksum** | 2 Bytes | `uint16` (BE) | Lower 16 bits of standard CRC-32 computed over header opcode, seq, and payload. |
| **Payload** | 0–120 Bytes | `bytes` | Compressed file fragment or encoded text data. |

### Operational Parameters

- **Audio Sampling Rate**: 48,000 Hz (48 kHz mono, `float32`).
- **Transfer Window Size**: 4 packets per batch.
- **Inter-Chirp Delay**: 150 ms between successive packets to allow room reverberation decay.
- **Post-Transmission Guard Delay**: 250 ms mute interval before activating receiver listening mode.
- **Maximum Retransmission Retries**: 5 attempts per unacknowledged frame.

---

## 4. Architectural Modularization

The codebase strictly adheres to modular separation of concerns:

```
ChirpDrop/
│
├── app/
│   ├── core/           # Binary packet framing, protocol definitions, CRC validation, parsing
│   ├── audio/          # Speaker output, microphone input, GGWave encoding and decoding
│   ├── communication/  # Text messaging, receiver dispatch loops, duplicate detection
│   ├── transfer/       # File compression, chunking, transfer state machine, reconstruction
│   ├── ui/             # PySide6 desktop interface (widgets, models, worker signals)
│   └── utils/          # Thread-safe logging, configuration helpers, path resolution
│
├── tests/              # Unit tests for protocol framing, chunking, CRC, and reassembly
├── received_files/     # Default directory for incoming reconstructed and verified files
├── logs/               # Application operational logs and diagnostic traces
├── docs/               # Architecture diagrams, protocol specifications, user guides
│
├── requirements.txt    # Python runtime and build dependencies
├── main.py             # Minimal non-blocking application bootstrap entry point
├── config.py           # Centralized configuration parameters and constants
├── .gitignore          # Version control filtering rules
└── README.md           # Master project documentation
```

### Module Responsibilities

| Subsystem | Folder | Key Responsibilities |
| :--- | :--- | :--- |
| **Protocol Core** | `app/core` | Serializes and deserializes binary headers, validates the `CD\x01` preamble, verifies CRC checksums, and parses raw byte buffers. |
| **Audio I/O** | `app/audio` | Wraps PortAudio (`sounddevice`) for non-blocking stream capture and playback. Interfaces with `ggwave` for acoustic waveform synthesis and analysis. |
| **Communication** | `app/communication` | Handles real-time messaging, sequence number tracking, deduplication caches, and peer discovery/SYN handshakes. |
| **Transfer Engine** | `app/transfer` | Manages file segmentation, Zlib compression, sliding-window flow control, retransmission timers, and SHA-256 validation upon file assembly. |
| **User Interface** | `app/ui` | PySide6-based graphical interface with progress indicators, audio level meters, transfer history, and device selection. |
| **Utilities** | `app/utils` | Shared loggers, filesystem helpers, and platform-specific helpers. |

---

## 5. Technology Stack & Dependencies

| Component | Library / Tool | Version | Purpose |
| :--- | :--- | :--- | :--- |
| **Runtime** | Python | `3.11.x` | Target language runtime for Windows 10 & 11. |
| **UI Framework** | PySide6 | `^6.5.0` | Official Qt 6 desktop bindings (Native Windows controls). |
| **Audio Hardware I/O** | sounddevice | `^0.4.6` | PortAudio wrapper providing low-latency audio capture and playback. |
| **Numerical Processing** | numpy | `^1.24.0, <2.0.0` | Audio buffer arrays and fast signal transformations. |
| **Modulation / FSK** | ggwave | `^0.4.0` | Acoustic data modulation/demodulation engine. |
| **Binary Serialization** | `struct` | Standard Library | Fixed-width struct encoding and decoding. |
| **Integrity & Checksum** | `zlib`, `hashlib` | Standard Library | CRC-16 computation and SHA-256 cryptographic verification. |
| **Concurrency** | `threading`, `queue` | Standard Library | Safe background audio streaming decoupled from Qt event loop. |

---

## 6. Installation & Environment Setup

### Prerequisites
- Windows 10 (Build 19041+) or Windows 11.
- Python 3.11 64-bit installed with PATH configured.
- Working audio input (microphone) and output (speakers).

### Step-by-Step Installation

1. **Clone or Extract Project Directory**:
   ```powershell
   cd ChirpDrop
   ```

2. **Create and Activate Virtual Environment**:
   ```powershell
   python -m venv .venv
   .\.venv\Scripts\Activate.ps1
   ```

3. **Install Dependencies**:
   ```powershell
   pip install --upgrade pip setuptools wheel
   pip install -r requirements.txt
   ```

4. **Verify Configuration**:
   ```powershell
   python main.py --check-config
   ```

---

## 7. Acoustic Transmission Considerations

To achieve dependable transfers in air-gapped environments:

1. **Acoustic Feedback Isolation**:
   - The transmitting station temporarily mutes or disregards microphone input during its transmission window.
   - The mandatory `POST_TRANSMISSION_GUARD_MS` (250 ms) ensures internal echo and speaker decay dissipate before the receiver loop resumes.
2. **Frequency Selection**:
   - Use **Audible Mode** in reverberant conference rooms or when using basic laptop speakers that exhibit steep attenuation above 16 kHz.
   - Use **Ultrasonic Mode** when quiet operation is required and both machines feature microphones/speakers validated up to 20 kHz.
3. **Physical Distance**:
   - Optimal transfer distance is 0.5 to 2.5 meters.
   - Direct line-of-sight between speakers and microphones minimizes multi-path fading.

---

## 8. Development Roadmap

- [x] **Task 01: Project Architecture & Initialization** (Current)
- [ ] **Task 02: Core Protocol & Binary Packet Serialization** (`app/core`)
- [ ] **Task 03: Audio Engine & GGWave Acoustic Modulation** (`app/audio`)
- [ ] **Task 04: Communication Layer & Message Exchange** (`app/communication`)
- [ ] **Task 05: Reliable File Transfer Engine & Sliding Window** (`app/transfer`)
- [ ] **Task 06: PySide6 Desktop User Interface** (`app/ui`)
- [ ] **Task 07: Integration, Loopback Testing & Field Validation**
