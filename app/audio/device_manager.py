"""
ChirpDrop - Audio Device Manager
--------------------------------
Handles audio input and output device enumeration, querying, capability testing,
and hardware validation using SoundDevice (PortAudio wrapper).
"""

from dataclasses import dataclass
import logging
from typing import Dict, List, Optional, Tuple, Union
import sounddevice as sd

logger = logging.getLogger("ChirpDrop.AudioDeviceManager")


# ---------------------------------------------------------------------------
# Custom Exceptions
# ---------------------------------------------------------------------------
class AudioDeviceError(Exception):
    """Base exception for audio device management errors."""


class DeviceNotFoundError(AudioDeviceError):
    """Raised when a requested audio device cannot be located."""


class DeviceConfigurationError(AudioDeviceError):
    """Raised when an audio device does not support the required configuration."""


# ---------------------------------------------------------------------------
# Device Information Dataclass
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class AudioDeviceInfo:
    """
    Structured metadata representing an audio endpoint.

    Attributes:
        index: SoundDevice integer identifier for the device.
        name: Hardware / driver reported device name.
        host_api_index: PortAudio host API index (MME, WASAPI, etc.).
        host_api_name: Human-readable host API name.
        max_input_channels: Maximum input channels supported.
        max_output_channels: Maximum output channels supported.
        default_sample_rate: Hardware default sampling rate in Hz.
        is_default_input: Whether this device is currently the OS default input.
        is_default_output: Whether this device is currently the OS default output.
    """

    index: int
    name: str
    host_api_index: int
    host_api_name: str
    max_input_channels: int
    max_output_channels: int
    default_sample_rate: float
    is_default_input: bool = False
    is_default_output: bool = False

    @property
    def is_input(self) -> bool:
        """True if the device supports at least one audio input channel."""
        return self.max_input_channels > 0

    @property
    def is_output(self) -> bool:
        """True if the device supports at least one audio output channel."""
        return self.max_output_channels > 0


# ---------------------------------------------------------------------------
# Audio Device Manager Class
# ---------------------------------------------------------------------------
class AudioDeviceManager:
    """
    Manages querying, capability validation, and lifecycle monitoring of
    system audio input and output endpoints.
    """

    def __init__(self) -> None:
        self._cached_devices: Optional[List[AudioDeviceInfo]] = None

    def _query_raw_devices(self) -> List[Dict]:
        """Query raw devices from SoundDevice safely."""
        try:
            raw = sd.query_devices()
            if isinstance(raw, dict):
                return [raw]
            return list(raw)
        except Exception as e:
            logger.error(f"Failed to query audio devices: {e}")
            raise AudioDeviceError(f"Failed to enumerate audio devices: {e}") from e

    def _get_host_apis(self) -> Dict[int, str]:
        """Query available PortAudio host APIs and map index to name."""
        try:
            apis = sd.query_hostapis()
            return {i: api.get("name", "Unknown") for i, api in enumerate(apis)}
        except Exception:
            return {}

    def refresh_devices(self) -> List[AudioDeviceInfo]:
        """
        Re-enumerate audio endpoints from the system hardware and return them.

        Returns:
            List of AudioDeviceInfo objects representing all discovered devices.
        """
        raw_devices = self._query_raw_devices()
        host_apis = self._get_host_apis()

        # Query default device indices
        default_in_idx: int = -1
        default_out_idx: int = -1
        try:
            default_pair = sd.default.device
            # Note: sounddevice._InputOutputPair supports indexing [0], [1] but has no len()
            default_in_idx = int(default_pair[0])
            default_out_idx = int(default_pair[1])
        except Exception:
            try:
                default_in_idx = default_out_idx = int(sd.default.device)
            except Exception as e:
                logger.debug(f"Could not determine default audio devices: {e}")

        devices: List[AudioDeviceInfo] = []
        for idx, dev in enumerate(raw_devices):
            api_idx = dev.get("hostapi", 0)
            api_name = host_apis.get(api_idx, "Unknown API")

            info = AudioDeviceInfo(
                index=idx,
                name=dev.get("name", f"Device #{idx}"),
                host_api_index=api_idx,
                host_api_name=api_name,
                max_input_channels=dev.get("max_input_channels", 0),
                max_output_channels=dev.get("max_output_channels", 0),
                default_sample_rate=float(dev.get("default_samplerate", 44100.0)),
                is_default_input=(idx == default_in_idx),
                is_default_output=(idx == default_out_idx),
            )
            devices.append(info)

        self._cached_devices = devices
        return devices

    def list_devices(self, refresh: bool = False) -> List[AudioDeviceInfo]:
        """
        Get all audio devices discovered on the workstation.

        Args:
            refresh: If True, forces a hardware re-enumeration.

        Returns:
            List of AudioDeviceInfo instances.
        """
        if self._cached_devices is None or refresh:
            return self.refresh_devices()
        return list(self._cached_devices)

    def list_input_devices(self, refresh: bool = False) -> List[AudioDeviceInfo]:
        """List all devices with input channel capability (microphones)."""
        return [dev for dev in self.list_devices(refresh=refresh) if dev.is_input]

    def list_output_devices(self, refresh: bool = False) -> List[AudioDeviceInfo]:
        """List all devices with output channel capability (speakers/headphones)."""
        return [dev for dev in self.list_devices(refresh=refresh) if dev.is_output]

    def get_default_input_device(self, refresh: bool = False) -> Optional[AudioDeviceInfo]:
        """
        Identify the primary default audio input device.

        Returns:
            AudioDeviceInfo if an active default input device exists, else None.
        """
        inputs = self.list_input_devices(refresh=refresh)
        for dev in inputs:
            if dev.is_default_input:
                return dev
        return inputs[0] if inputs else None

    def get_default_output_device(self, refresh: bool = False) -> Optional[AudioDeviceInfo]:
        """
        Identify the primary default audio output device.

        Returns:
            AudioDeviceInfo if an active default output device exists, else None.
        """
        outputs = self.list_output_devices(refresh=refresh)
        for dev in outputs:
            if dev.is_default_output:
                return dev
        return outputs[0] if outputs else None

    def get_device_by_index(self, index: int, refresh: bool = False) -> AudioDeviceInfo:
        """
        Lookup a device by its SoundDevice index.

        Raises:
            DeviceNotFoundError: If no device matches the provided index.
        """
        devices = self.list_devices(refresh=refresh)
        for dev in devices:
            if dev.index == index:
                return dev
        raise DeviceNotFoundError(f"Audio device with index {index} not found.")

    def get_device_by_name(
        self,
        name: str,
        is_input: Optional[bool] = None,
        refresh: bool = False,
    ) -> AudioDeviceInfo:
        """
        Lookup an audio device by full or partial name matching.

        Args:
            name: Exact or substring name to match (case-insensitive).
            is_input: If True, restricts search to inputs; if False, to outputs.
            refresh: If True, forces re-enumeration.

        Returns:
            Matching AudioDeviceInfo.

        Raises:
            DeviceNotFoundError: If no matching device is found.
        """
        devices = self.list_devices(refresh=refresh)
        name_lower = name.lower()

        for dev in devices:
            if is_input is True and not dev.is_input:
                continue
            if is_input is False and not dev.is_output:
                continue
            if name_lower in dev.name.lower():
                return dev

        target_type = "input" if is_input is True else ("output" if is_input is False else "any")
        raise DeviceNotFoundError(
            f"No {target_type} audio device matching '{name}' was found."
        )

    def check_format_support(
        self,
        device_index: int,
        sample_rate: int = 48000,
        channels: int = 1,
        dtype: str = "float32",
        is_input: bool = True,
    ) -> bool:
        """
        Determine if the specified hardware endpoint supports the given stream parameters.

        Args:
            device_index: Integer index of the target audio device.
            sample_rate: Sampling frequency in Hz (e.g. 48000).
            channels: Channel count (1 for mono, 2 for stereo).
            dtype: Sample representation ('float32', 'int16', etc.).
            is_input: True to test capture capability; False to test playback.

        Returns:
            True if supported without error, False otherwise.
        """
        try:
            if is_input:
                sd.check_input_settings(
                    device=device_index,
                    channels=channels,
                    dtype=dtype,
                    samplerate=sample_rate,
                )
            else:
                sd.check_output_settings(
                    device=device_index,
                    channels=channels,
                    dtype=dtype,
                    samplerate=sample_rate,
                )
            return True
        except Exception as e:
            logger.debug(
                f"Format check failed for device {device_index} (rate={sample_rate}, "
                f"ch={channels}, dtype={dtype}, input={is_input}): {e}"
            )
            return False

    def validate_input_device(
        self,
        device_index: int,
        sample_rate: int = 48000,
        channels: int = 1,
        dtype: str = "float32",
    ) -> AudioDeviceInfo:
        """
        Ensure an input device exists and supports the required format.

        Raises:
            DeviceNotFoundError: If the device does not exist.
            DeviceConfigurationError: If the device does not support recording or settings.
        """
        info = self.get_device_by_index(device_index)
        if not info.is_input:
            raise DeviceConfigurationError(
                f"Device #{device_index} ('{info.name}') has no input channels."
            )

        if not self.check_format_support(
            device_index, sample_rate=sample_rate, channels=channels, dtype=dtype, is_input=True
        ):
            raise DeviceConfigurationError(
                f"Input device #{device_index} ('{info.name}') does not support "
                f"{sample_rate} Hz, {channels} channel(s), {dtype} capture."
            )

        return info

    def validate_output_device(
        self,
        device_index: int,
        sample_rate: int = 48000,
        channels: int = 1,
        dtype: str = "float32",
    ) -> AudioDeviceInfo:
        """
        Ensure an output device exists and supports the required format.

        Raises:
            DeviceNotFoundError: If the device does not exist.
            DeviceConfigurationError: If the device does not support playback or settings.
        """
        info = self.get_device_by_index(device_index)
        if not info.is_output:
            raise DeviceConfigurationError(
                f"Device #{device_index} ('{info.name}') has no output channels."
            )

        if not self.check_format_support(
            device_index, sample_rate=sample_rate, channels=channels, dtype=dtype, is_input=False
        ):
            raise DeviceConfigurationError(
                f"Output device #{device_index} ('{info.name}') does not support "
                f"{sample_rate} Hz, {channels} channel(s), {dtype} playback."
            )

        return info
