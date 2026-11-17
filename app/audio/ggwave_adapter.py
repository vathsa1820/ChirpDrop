"""
ChirpDrop - GGWave Acoustic Data Modulation Adapter
---------------------------------------------------
Thread-safe adapter wrapping the native GGWave C-extension for encoding text/data
payloads into audio waveforms and incrementally decoding captured PCM buffers.
"""

import logging
import threading
from typing import Optional, Union
import ggwave

logger = logging.getLogger("ChirpDrop.GgWaveAdapter")

# Silence noisy native C++ stdout logs by default
try:
    ggwave.disableLog()
except Exception:
    pass


# ---------------------------------------------------------------------------
# Custom Exceptions
# ---------------------------------------------------------------------------
class GgWaveError(Exception):
    """Base exception for GGWave modulation and demodulation failures."""


class GgWaveInitError(GgWaveError):
    """Raised when native GGWave instance initialization fails."""


class GgWaveEncodeError(GgWaveError):
    """Raised when encoding a payload into an acoustic waveform fails."""


class GgWaveDecodeError(GgWaveError):
    """Raised when decoding audio PCM data fails due to a native error."""


# ---------------------------------------------------------------------------
# GGWave Protocol Constants
# ---------------------------------------------------------------------------
# Standard GGWave protocol IDs supported by the engine:
PROTOCOL_AUDIBLE_NORMAL = 0
PROTOCOL_AUDIBLE_FAST = 1
PROTOCOL_AUDIBLE_FASTEST = 2
PROTOCOL_ULTRASONIC_NORMAL = 3
PROTOCOL_ULTRASONIC_FAST = 4
PROTOCOL_ULTRASONIC_FASTEST = 5
PROTOCOL_DUALTONE_NORMAL = 6
PROTOCOL_DUALTONE_FAST = 7
PROTOCOL_DUALTONE_FASTEST = 8


# ---------------------------------------------------------------------------
# GgWaveAdapter Class
# ---------------------------------------------------------------------------
class GgWaveAdapter:
    """
    Manages an isolated GGWave native instance for acoustic modulation and
    demodulation with thread-safe lifecycle and resource management.
    """

    def __init__(
        self,
        sample_rate: int = 48000,
        default_protocol_id: int = PROTOCOL_AUDIBLE_NORMAL,
        default_volume: int = 20,
    ) -> None:
        """
        Initialize the adapter configuration.

        Args:
            sample_rate: Sampling frequency in Hz (default: 48000).
            default_protocol_id: Default modulation protocol (0: Audible Normal, 3: Ultrasonic).
            default_volume: Default output gain percentage (1 to 100).
        """
        self._sample_rate = sample_rate
        self._default_protocol_id = default_protocol_id
        self._default_volume = max(1, min(100, default_volume))

        self._instance: Optional[int] = None
        self._lock = threading.Lock()

    @property
    def is_initialized(self) -> bool:
        """Check whether the native GGWave instance handle is active."""
        with self._lock:
            return self._instance is not None

    @property
    def instance_id(self) -> Optional[int]:
        """Return the active native instance identifier, if initialized."""
        with self._lock:
            return self._instance

    def initialize(self) -> int:
        """
        Initialize a dedicated native GGWave instance handle.

        Returns:
            Native instance handle integer.

        Raises:
            GgWaveInitError: If the native engine fails to initialize.
        """
        with self._lock:
            if self._instance is not None:
                return self._instance

            try:
                params = ggwave.getDefaultParameters()
                params["sampleRate"] = float(self._sample_rate)
                params["sampleRateInp"] = float(self._sample_rate)
                params["sampleRateOut"] = float(self._sample_rate)

                handle = ggwave.init(params)
                if handle is None or handle < 0:
                    raise GgWaveInitError("ggwave.init() returned invalid handle.")

                self._instance = handle
                logger.debug(f"Initialized native GGWave instance handle: {handle}")
                return handle
            except Exception as e:
                logger.error(f"Failed to initialize GGWave instance: {e}")
                raise GgWaveInitError(f"Native GGWave initialization failed: {e}") from e

    def close(self) -> None:
        """Safely release the native GGWave instance handle and free memory."""
        with self._lock:
            if self._instance is not None:
                try:
                    ggwave.free(self._instance)
                    logger.debug(f"Freed native GGWave instance handle: {self._instance}")
                except Exception as e:
                    logger.warning(f"Error freeing GGWave instance #{self._instance}: {e}")
                finally:
                    self._instance = None

    def __enter__(self) -> "GgWaveAdapter":
        self.initialize()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.close()

    def encode(
        self,
        payload: Union[str, bytes],
        protocol_id: Optional[int] = None,
        volume: Optional[int] = None,
    ) -> bytes:
        """
        Encode text or binary data into an acoustic PCM waveform.

        Note on GGWave API constraints:
            The underlying GGWave Cython extension signature expects a `str` payload
            and encodes it via UTF-8 into the C++ engine. If `bytes` are provided,
            the adapter will attempt a UTF-8 decoding. If raw binary bytes contain
            invalid UTF-8 byte sequences, a GgWaveEncodeError is raised with advice
            to use text-safe encoding (e.g. Base64 or ASCII Hex).

        Args:
            payload: String message or valid UTF-8 byte sequence to transmit.
            protocol_id: GGWave protocol ID (default: instance configured protocol).
            volume: Audio amplitude percentage (1 to 100).

        Returns:
            Raw audio waveform bytes representing 32-bit floating-point mono PCM samples.

        Raises:
            GgWaveEncodeError: If payload cannot be encoded or native engine fails.
        """
        # Resolve string representation
        if isinstance(payload, bytes):
            try:
                text_payload = payload.decode("utf-8")
            except UnicodeDecodeError as err:
                raise GgWaveEncodeError(
                    "GGWave native API accepts string payloads encoded as UTF-8. "
                    "For arbitrary binary payloads containing non-UTF8 bytes, encode "
                    "using Base64 or ASCII hex before passing to the adapter."
                ) from err
        elif isinstance(payload, str):
            text_payload = payload
        else:
            raise GgWaveEncodeError(
                f"Payload must be str or bytes, got {type(payload).__name__}"
            )

        if not text_payload:
            raise GgWaveEncodeError("Cannot encode an empty payload.")

        pid = self._default_protocol_id if protocol_id is None else protocol_id
        vol = self._default_volume if volume is None else max(1, min(100, volume))

        try:
            # Note: ggwave.encode takes (payload, protocolId, volume, instance)
            waveform = ggwave.encode(
                text_payload,
                protocolId=pid,
                volume=vol,
                instance=self._instance,
            )
            if not waveform or len(waveform) == 0:
                raise GgWaveEncodeError("ggwave.encode returned an empty waveform.")
            return waveform
        except Exception as e:
            if isinstance(e, GgWaveEncodeError):
                raise
            logger.error(f"GGWave encode failed: {e}")
            raise GgWaveEncodeError(f"Acoustic waveform generation failed: {e}") from e

    def decode(self, pcm_data: bytes) -> Optional[bytes]:
        """
        Feed an incoming buffer of PCM audio samples into the demodulation engine.

        The native GGWave engine processes audio frames incrementally and returns
        the decoded payload bytes as soon as a complete transmission end marker
        is identified.

        Args:
            pcm_data: Audio bytes representing float32 samples (multiple of 4 bytes).

        Returns:
            Decoded payload as `bytes` if a transmission was completed and decoded,
            or `None` if more audio samples are required.

        Raises:
            GgWaveDecodeError: If decoding fails or instance is not initialized.
        """
        if not pcm_data:
            return None

        # Sample size validation: float32 = 4 bytes per sample
        if len(pcm_data) % 4 != 0:
            # Trim to the nearest 4-byte boundary to avoid native assertion failure
            valid_len = (len(pcm_data) // 4) * 4
            if valid_len == 0:
                return None
            pcm_data = pcm_data[:valid_len]

        with self._lock:
            if self._instance is None:
                raise GgWaveDecodeError(
                    "Cannot decode audio: GgWaveAdapter is not initialized."
                )

            try:
                result = ggwave.decode(self._instance, pcm_data)
                return result
            except Exception as e:
                logger.error(f"GGWave decode failed: {e}")
                raise GgWaveDecodeError(f"Demodulation processing failed: {e}") from e

    def rx_toggle_protocol(self, protocol_id: int, enabled: bool) -> None:
        """
        Enable or disable a specific reception protocol in the decoder.

        Args:
            protocol_id: Integer protocol ID (e.g. 0 for Audible, 3 for Ultrasonic).
            enabled: True to enable listening; False to ignore this protocol.
        """
        with self._lock:
            try:
                ggwave.rxToggleProtocol(protocol_id, 1 if enabled else 0)
            except Exception as e:
                logger.warning(f"Failed to toggle rx protocol {protocol_id}: {e}")

    def tx_toggle_protocol(self, protocol_id: int, enabled: bool) -> None:
        """
        Enable or disable a specific transmission protocol.

        Args:
            protocol_id: Integer protocol ID.
            enabled: True to enable; False to disable.
        """
        with self._lock:
            try:
                ggwave.txToggleProtocol(protocol_id, 1 if enabled else 0)
            except Exception as e:
                logger.warning(f"Failed to toggle tx protocol {protocol_id}: {e}")
