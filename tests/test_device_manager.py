"""
ChirpDrop - Unit Tests for Audio Device Manager
-----------------------------------------------
Tests audio hardware querying, format compatibility validation,
and missing or malformed device error handling.
"""

from unittest.mock import MagicMock, patch
import pytest

from app.audio.device_manager import (
    AudioDeviceError,
    AudioDeviceInfo,
    AudioDeviceManager,
    DeviceConfigurationError,
    DeviceNotFoundError,
)


MOCK_RAW_DEVICES = [
    {
        "name": "Mock Microphone Array",
        "hostapi": 0,
        "max_input_channels": 2,
        "max_output_channels": 0,
        "default_samplerate": 48000.0,
    },
    {
        "name": "Mock Stereo Speakers",
        "hostapi": 0,
        "max_input_channels": 0,
        "max_output_channels": 2,
        "default_samplerate": 48000.0,
    },
    {
        "name": "Mock Legacy In/Out Headset",
        "hostapi": 1,
        "max_input_channels": 1,
        "max_output_channels": 1,
        "default_samplerate": 44100.0,
    },
]

MOCK_HOST_APIS = (
    {"name": "Windows WASAPI", "default_input_device": 0, "default_output_device": 1},
    {"name": "MME", "default_input_device": 2, "default_output_device": 2},
)


@pytest.fixture
def mock_sd():
    """Patch sounddevice device query functions with controlled test data."""
    import sounddevice as sd
    with patch("sounddevice.query_devices", return_value=MOCK_RAW_DEVICES), \
         patch("sounddevice.query_hostapis", return_value=MOCK_HOST_APIS), \
         patch.object(sd.default, "device", [0, 1]):
        yield


def test_device_enumeration(mock_sd) -> None:
    """Verify listing and segregation of input and output audio endpoints."""
    manager = AudioDeviceManager()
    devices = manager.list_devices(refresh=True)

    assert len(devices) == 3
    assert devices[0].name == "Mock Microphone Array"
    assert devices[0].is_input
    assert not devices[0].is_output
    assert devices[0].is_default_input

    assert devices[1].name == "Mock Stereo Speakers"
    assert not devices[1].is_input
    assert devices[1].is_output
    assert devices[1].is_default_output

    inputs = manager.list_input_devices()
    assert len(inputs) == 2
    assert inputs[0].index == 0
    assert inputs[1].index == 2

    outputs = manager.list_output_devices()
    assert len(outputs) == 2
    assert outputs[0].index == 1
    assert outputs[1].index == 2


def test_get_default_devices(mock_sd) -> None:
    """Verify identification of system default microphone and speaker."""
    manager = AudioDeviceManager()
    default_in = manager.get_default_input_device()
    default_out = manager.get_default_output_device()

    assert default_in is not None
    assert default_in.index == 0
    assert default_in.name == "Mock Microphone Array"

    assert default_out is not None
    assert default_out.index == 1
    assert default_out.name == "Mock Stereo Speakers"


def test_get_device_by_index_and_name(mock_sd) -> None:
    """Test retrieval by integer index and fuzzy name matching."""
    manager = AudioDeviceManager()

    dev = manager.get_device_by_index(1)
    assert dev.name == "Mock Stereo Speakers"

    dev_name = manager.get_device_by_name("speakers")
    assert dev_name.index == 1

    dev_mic = manager.get_device_by_name("microphone", is_input=True)
    assert dev_mic.index == 0


def test_missing_device_handling(mock_sd) -> None:
    """Verify that querying nonexistent devices raises DeviceNotFoundError."""
    manager = AudioDeviceManager()

    with pytest.raises(DeviceNotFoundError, match="index 999 not found"):
        manager.get_device_by_index(999)

    with pytest.raises(DeviceNotFoundError, match="No input audio device"):
        manager.get_device_by_name("Nonexistent Microphone", is_input=True)


def test_format_validation(mock_sd) -> None:
    """Test format validation checks for input and output devices."""
    manager = AudioDeviceManager()

    with patch("sounddevice.check_input_settings", return_value=None):
        info = manager.validate_input_device(0, sample_rate=48000, channels=1)
        assert info.index == 0

    # Device 1 is output-only, validating as input should raise DeviceConfigurationError
    with pytest.raises(DeviceConfigurationError, match="has no input channels"):
        manager.validate_input_device(1)

    # When format check fails
    with patch("sounddevice.check_input_settings", side_effect=Exception("Unsupported rate")):
        with pytest.raises(DeviceConfigurationError, match="does not support"):
            manager.validate_input_device(0, sample_rate=96000)
