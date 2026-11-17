"""
ChirpDrop - Centralized Configuration Module
-------------------------------------------
Defines all system-wide constants, protocol specifications, timing constraints,
filesystem paths, and acoustic modulation profiles for air-gapped acoustic
communication on Windows systems.
"""

from dataclasses import dataclass
from enum import Enum, IntEnum
from pathlib import Path
from typing import Dict, Final, Tuple

# ---------------------------------------------------------------------------
# Application Metadata
# ---------------------------------------------------------------------------
APPLICATION_NAME: Final[str] = "ChirpDrop"
APPLICATION_VERSION: Final[str] = "0.1.0"
ORGANIZATION_NAME: Final[str] = "ChirpDrop Systems"

# ---------------------------------------------------------------------------
# Filesystem Paths (pathlib.Path)
# ---------------------------------------------------------------------------
BASE_DIR: Final[Path] = Path(__file__).resolve().parent
APP_DIR: Final[Path] = BASE_DIR / "app"
CORE_DIR: Final[Path] = APP_DIR / "core"
AUDIO_DIR: Final[Path] = APP_DIR / "audio"
COMMUNICATION_DIR: Final[Path] = APP_DIR / "communication"
TRANSFER_DIR: Final[Path] = APP_DIR / "transfer"
UI_DIR: Final[Path] = APP_DIR / "ui"
UTILS_DIR: Final[Path] = APP_DIR / "utils"

RECEIVED_FILES_DIR: Final[Path] = BASE_DIR / "received_files"
LOGS_DIR: Final[Path] = BASE_DIR / "logs"
DOCS_DIR: Final[Path] = BASE_DIR / "docs"
TESTS_DIR: Final[Path] = BASE_DIR / "tests"

# ---------------------------------------------------------------------------
# Audio Hardware & Sampling Parameters
# ---------------------------------------------------------------------------
SAMPLE_RATE: Final[int] = 48000  # 48 kHz standard across Windows audio devices
CHANNELS: Final[int] = 1        # Monophonic acoustic transmission
AUDIO_DTYPE: Final[str] = "float32"

# ---------------------------------------------------------------------------
# Protocol Framing & Binary Packet Sizing
# ---------------------------------------------------------------------------
# Header Specification (8 bytes total):
# +-------------------+---------------+--------------------+------------------+
# | Magic Preamble    | Opcode        | Sequence Number    | Checksum         |
# | b"CD\x01" (3B)    | uint8 (1B)    | uint16 (2B)        | uint16 (2B)      |
# +-------------------+---------------+--------------------+------------------+
MAGIC_PREAMBLE: Final[bytes] = b"CD\x01"  # 3-byte unique packet identifier
HEADER_SIZE: Final[int] = 8                # 3 + 1 + 2 + 2 = 8 bytes
MAX_PAYLOAD_SIZE: Final[int] = 120         # Maximum payload chunk per packet
MAX_PACKET_SIZE: Final[int] = 128          # HEADER_SIZE + MAX_PAYLOAD_SIZE

# ---------------------------------------------------------------------------
# Flow Control & Timing Constraints
# ---------------------------------------------------------------------------
TRANSFER_WINDOW_SIZE: Final[int] = 4       # Sliding window size in packets
INTER_CHIRP_DELAY_MS: Final[int] = 150     # Delay between consecutive packets (ms)
POST_TRANSMISSION_GUARD_MS: Final[int] = 250  # Guard delay to prevent speaker/mic feedback (ms)
ACK_TIMEOUT_MS: Final[int] = 2500          # Timeout waiting for ACK/NACK (ms)
MAX_RETRANSMISSION_ATTEMPTS: Final[int] = 5

# ---------------------------------------------------------------------------
# Protocol Opcodes
# ---------------------------------------------------------------------------
class Opcode(IntEnum):
    """Protocol operation codes embedded at byte 3 of the packet header."""
    SYN = 0x01   # Session synchronization and transfer negotiation
    DATA = 0x02  # Fragmented file or message payload packet
    NACK = 0x03  # Negative acknowledgment requesting selective retransmission
    FIN = 0x04   # Finalization and session closure


# ---------------------------------------------------------------------------
# Acoustic Transmission Profiles (Audible vs. Ultrasonic)
# ---------------------------------------------------------------------------
class TransmissionMode(str, Enum):
    """Operating acoustic transmission modes."""
    AUDIBLE = "audible"
    ULTRASONIC = "ultrasonic"


@dataclass(frozen=True)
class AudioProfileConfig:
    """Configuration profile for a specific acoustic modulation mode."""
    mode: TransmissionMode
    name: str
    description: str
    frequency_range_hz: Tuple[int, int]
    ggwave_protocol_id: int  # GGWave protocol identifier index
    default_volume: float    # Normalised amplitude gain (0.0 - 1.0)
    sample_rate: int = SAMPLE_RATE


# Audible Profile:
# Frequencies ~1.5 kHz to 15 kHz. Highly resilient against background ambient noise,
# room reverberation, and lower-grade laptop speakers/microphones.
AUDIBLE_CONFIG: Final[AudioProfileConfig] = AudioProfileConfig(
    mode=TransmissionMode.AUDIBLE,
    name="Audible Fast",
    description="Audible band acoustic modulation (Fast protocol ID 1).",
    frequency_range_hz=(1500, 15000),
    ggwave_protocol_id=1,  # GGWAVE_TX_PROTOCOL_AUDIBLE_FAST (Protocol ID 1)
    default_volume=0.80,
    sample_rate=SAMPLE_RATE,
)

# Ultrasonic Profile:
# Near-ultrasound band ~15 kHz to 20 kHz. Inaudible to human ears.
# Requires clean high-frequency response on both transmitting speaker and receiving microphone.
ULTRASONIC_CONFIG: Final[AudioProfileConfig] = AudioProfileConfig(
    mode=TransmissionMode.ULTRASONIC,
    name="Near-Ultrasonic Normal",
    description="Near-ultrasonic acoustic modulation (15-20 kHz). Human-inaudible transmission.",
    frequency_range_hz=(15000, 20000),
    ggwave_protocol_id=3,  # GGWAVE_TX_PROTOCOL_ULTRASONIC_NORMAL
    default_volume=1.00,   # Maximum volume recommended to offset high-frequency speaker rolloff
    sample_rate=SAMPLE_RATE,
)

AUDIO_PROFILES: Final[Dict[TransmissionMode, AudioProfileConfig]] = {
    TransmissionMode.AUDIBLE: AUDIBLE_CONFIG,
    TransmissionMode.ULTRASONIC: ULTRASONIC_CONFIG,
}

DEFAULT_TRANSMISSION_MODE: Final[TransmissionMode] = TransmissionMode.AUDIBLE
