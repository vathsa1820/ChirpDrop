"""
ChirpDrop - Audio Subsystem Package
-----------------------------------
Exports the real-time audio engine, device manager, and GGWave acoustic modem adapter.
"""

from app.audio.device_manager import (
    AudioDeviceError,
    AudioDeviceInfo,
    AudioDeviceManager,
    DeviceConfigurationError,
    DeviceNotFoundError,
)
from app.audio.ggwave_adapter import (
    PROTOCOL_AUDIBLE_FAST,
    PROTOCOL_AUDIBLE_FASTEST,
    PROTOCOL_AUDIBLE_NORMAL,
    PROTOCOL_DUALTONE_FAST,
    PROTOCOL_DUALTONE_FASTEST,
    PROTOCOL_DUALTONE_NORMAL,
    PROTOCOL_ULTRASONIC_FAST,
    PROTOCOL_ULTRASONIC_FASTEST,
    PROTOCOL_ULTRASONIC_NORMAL,
    GgWaveAdapter,
    GgWaveDecodeError,
    GgWaveEncodeError,
    GgWaveError,
    GgWaveInitError,
)
from app.audio.audio_engine import AudioEngine, AudioEngineError

__all__ = [
    # Device Management
    "AudioDeviceManager",
    "AudioDeviceInfo",
    "AudioDeviceError",
    "DeviceNotFoundError",
    "DeviceConfigurationError",
    # GGWave Adapter & Protocols
    "GgWaveAdapter",
    "GgWaveError",
    "GgWaveInitError",
    "GgWaveEncodeError",
    "GgWaveDecodeError",
    "PROTOCOL_AUDIBLE_NORMAL",
    "PROTOCOL_AUDIBLE_FAST",
    "PROTOCOL_AUDIBLE_FASTEST",
    "PROTOCOL_ULTRASONIC_NORMAL",
    "PROTOCOL_ULTRASONIC_FAST",
    "PROTOCOL_ULTRASONIC_FASTEST",
    "PROTOCOL_DUALTONE_NORMAL",
    "PROTOCOL_DUALTONE_FAST",
    "PROTOCOL_DUALTONE_FASTEST",
    # Audio Engine
    "AudioEngine",
    "AudioEngineError",
]
