"""
ChirpDrop - Real-Time Audio Engine
----------------------------------
Manages full-duplex non-blocking audio capture, transmission playback,
echo suppression, and asynchronous demodulation worker pipeline.
"""

from collections.abc import Callable
import logging
import queue
import threading
import time
from typing import Final, List, Optional, Union
import numpy as np
import sounddevice as sd

import config
from config import TransmissionMode
from app.audio.device_manager import AudioDeviceInfo, AudioDeviceManager
from app.audio.ggwave_adapter import (
    GgWaveAdapter,
    PROTOCOL_AUDIBLE_NORMAL,
    PROTOCOL_ULTRASONIC_NORMAL,
)

logger = logging.getLogger("ChirpDrop.AudioEngine")


# ---------------------------------------------------------------------------
# Custom Exceptions
# ---------------------------------------------------------------------------
class AudioEngineError(Exception):
    """Base exception for audio engine runtime errors."""


# ---------------------------------------------------------------------------
# Audio Engine Implementation
# ---------------------------------------------------------------------------
class AudioEngine:
    """
    Coordinates hardware audio streams with the GGWave acoustic modem.

    Key Architectural Principles:
      1. Non-blocking audio capture: The SoundDevice audio callback performs only
         lightweight buffer copying into a bounded queue and returns immediately.
      2. Asynchronous decoding: A dedicated worker thread pulls PCM blocks from the
         queue and processes them through the GGWave demodulation adapter.
      3. Acoustic echo suppression: Incoming microphone decoding is suppressed
         during local speaker playback plus a configurable post-transmission guard delay.
    """

    DEFAULT_BLOCK_SIZE: Final[int] = 1024  # 1024 frames = 4096 bytes (float32 mono)
    DEFAULT_QUEUE_MAXSIZE: Final[int] = 150  # ~3.2 seconds of buffer headroom

    def __init__(
        self,
        input_device_index: Optional[int] = None,
        output_device_index: Optional[int] = None,
        sample_rate: int = config.SAMPLE_RATE,
        channels: int = config.CHANNELS,
        block_size: int = DEFAULT_BLOCK_SIZE,
        guard_delay_ms: int = config.POST_TRANSMISSION_GUARD_MS,
        transmission_mode: TransmissionMode = config.DEFAULT_TRANSMISSION_MODE,
    ) -> None:
        """
        Initialize the audio engine components.

        Args:
            input_device_index: Selected input device index (None for OS default).
            output_device_index: Selected output device index (None for OS default).
            sample_rate: Audio sampling frequency in Hz (default: 48000).
            channels: Monophonic capture/playback (default: 1).
            block_size: Frame count per audio callback block (default: 1024).
            guard_delay_ms: Post-transmission silence duration in ms (default: 250).
            transmission_mode: TransmissionMode.AUDIBLE or TransmissionMode.ULTRASONIC.
        """
        self._sample_rate = sample_rate
        self._channels = channels
        self._block_size = block_size
        self._guard_delay_sec = guard_delay_ms / 1000.0

        self._device_manager = AudioDeviceManager()
        self._input_device = input_device_index
        self._output_device = output_device_index

        self._transmission_mode = transmission_mode
        self._adapter: Optional[GgWaveAdapter] = None

        # Concurrency & Streaming State
        self._stream: Optional[sd.InputStream] = None
        self._audio_queue: queue.Queue[bytes] = queue.Queue(maxsize=self.DEFAULT_QUEUE_MAXSIZE)
        self.received_queue: queue.Queue[bytes] = queue.Queue()
        self._callbacks: List[Callable[[bytes], None]] = []

        self._running = False
        self._decoder_thread: Optional[threading.Thread] = None
        self._dropped_blocks = 0

        # Echo & Transmission State Control
        self._is_transmitting = False
        self._tx_finished_time = 0.0
        self._tx_lock = threading.Lock()

    # -----------------------------------------------------------------------
    # Properties & Status Accessors
    # -----------------------------------------------------------------------
    @property
    def is_running(self) -> bool:
        """True if the audio capture stream and background worker are active."""
        return self._running

    @property
    def dropped_blocks_count(self) -> int:
        """Total number of audio blocks dropped due to queue congestion."""
        return self._dropped_blocks

    @property
    def transmission_mode(self) -> TransmissionMode:
        """Current operating transmission mode (Audible or Ultrasonic)."""
        return self._transmission_mode

    @property
    def input_device_index(self) -> Optional[int]:
        """Index of the active or configured input audio device."""
        return self._input_device

    @property
    def output_device_index(self) -> Optional[int]:
        """Index of the active or configured output audio device."""
        return self._output_device

    def set_transmission_mode(self, mode: TransmissionMode) -> None:
        """
        Switch between Audible and Ultrasonic transmission profiles.

        Args:
            mode: Desired TransmissionMode enum value.
        """
        self._transmission_mode = mode
        if self._adapter and self._adapter.is_initialized:
            proto_id = self._get_active_protocol_id()
            self._adapter.rx_toggle_protocol(proto_id, True)
            logger.info(f"Switched transmission mode to {mode.value} (protocol #{proto_id})")

    def _get_active_protocol_id(self) -> int:
        """Map active transmission profile to GGWave protocol identifier."""
        if self._transmission_mode == TransmissionMode.ULTRASONIC:
            return config.ULTRASONIC_CONFIG.ggwave_protocol_id
        return config.AUDIBLE_CONFIG.ggwave_protocol_id

    def _get_active_volume(self) -> int:
        """Get integer percentage volume gain for active profile."""
        if self._transmission_mode == TransmissionMode.ULTRASONIC:
            return int(round(config.ULTRASONIC_CONFIG.default_volume * 100))
        return int(round(config.AUDIBLE_CONFIG.default_volume * 100))

    def register_callback(self, callback: Callable[[bytes], None]) -> None:
        """
        Register a consumer callback invoked whenever a message is demodulated.

        Args:
            callback: Callable accepting decoded bytes.
        """
        if callback not in self._callbacks:
            self._callbacks.append(callback)

    def unregister_callback(self, callback: Callable[[bytes], None]) -> None:
        """Remove a previously registered payload consumer callback."""
        if callback in self._callbacks:
            self._callbacks.remove(callback)

    # -----------------------------------------------------------------------
    # Transmission State & Echo Suppression Mechanism
    # -----------------------------------------------------------------------
    def is_suppressed(self) -> bool:
        """
        Determine whether incoming audio demodulation should be suppressed
        to prevent acoustic feedback or loopback from speaker to microphone.

        Returns:
            True if local transmission is ongoing or within the post-transmission guard delay.
        """
        with self._tx_lock:
            if self._is_transmitting:
                return True
            if self._tx_finished_time > 0.0:
                elapsed = time.monotonic() - self._tx_finished_time
                if elapsed < self._guard_delay_sec:
                    return True
        return False

    def get_suppression_status(self) -> dict:
        """Retrieve detailed diagnostic metrics for transmission state control."""
        with self._tx_lock:
            now = time.monotonic()
            is_tx = self._is_transmitting
            elapsed = (now - self._tx_finished_time) if self._tx_finished_time > 0 else 0.0
            in_guard = not is_tx and (elapsed < self._guard_delay_sec) and (self._tx_finished_time > 0)
        return {
            "is_transmitting": is_tx,
            "in_guard_period": in_guard,
            "guard_remaining_sec": max(0.0, self._guard_delay_sec - elapsed) if in_guard else 0.0,
            "is_suppressed": is_tx or in_guard,
        }

    # -----------------------------------------------------------------------
    # Hardware Audio Stream Lifecycle
    # -----------------------------------------------------------------------
    def start_capture(self) -> None:
        """
        Start microphone capture stream and launch the background demodulation worker.

        Raises:
            AudioEngineError: If audio devices fail or stream cannot open.
        """
        if self._running:
            logger.warning("start_capture() called while AudioEngine is already running.")
            return

        # Resolve and validate input device
        try:
            if self._input_device is None:
                default_in = self._device_manager.get_default_input_device()
                if not default_in:
                    raise AudioEngineError("No audio input device found on the system.")
                self._input_device = default_in.index

            self._device_manager.validate_input_device(
                self._input_device,
                sample_rate=self._sample_rate,
                channels=self._channels,
                dtype="float32",
            )
        except Exception as e:
            logger.error(f"Input device validation failed: {e}")
            raise AudioEngineError(f"Audio input setup failed: {e}") from e

        # Initialize GGWave adapter
        if self._adapter is None:
            self._adapter = GgWaveAdapter(
                sample_rate=self._sample_rate,
                default_protocol_id=self._get_active_protocol_id(),
                default_volume=self._get_active_volume(),
            )
        self._adapter.initialize()

        # Clear queues
        while not self._audio_queue.empty():
            try:
                self._audio_queue.get_nowait()
            except queue.Empty:
                break
        self._dropped_blocks = 0

        # Launch background decoder thread
        self._running = True
        self._decoder_thread = threading.Thread(
            target=self._decoder_worker,
            name="ChirpDrop-AudioDecoderWorker",
            daemon=True,
        )
        self._decoder_thread.start()

        # Open non-blocking PortAudio input stream
        try:
            self._stream = sd.InputStream(
                samplerate=self._sample_rate,
                channels=self._channels,
                dtype="float32",
                device=self._input_device,
                blocksize=self._block_size,
                callback=self._audio_callback,
            )
            self._stream.start()
            logger.info(
                f"Audio capture started: Device #{self._input_device}, "
                f"Rate={self._sample_rate} Hz, Channels={self._channels}, Block={self._block_size}"
            )
        except Exception as e:
            self._running = False
            if self._decoder_thread and self._decoder_thread.is_alive():
                self._decoder_thread.join(timeout=1.0)
            if self._adapter:
                self._adapter.close()
            logger.error(f"Failed to start SoundDevice InputStream: {e}")
            raise AudioEngineError(f"Failed to open audio input stream: {e}") from e

    def stop_capture(self) -> None:
        """
        Halt audio input capture stream, drain worker, and free native resources cleanly.
        """
        if not self._running:
            return

        logger.info("Stopping audio capture and decoder worker...")
        self._running = False

        # Stop audio hardware stream
        if self._stream:
            try:
                self._stream.stop()
                self._stream.close()
            except Exception as e:
                logger.warning(f"Error closing audio input stream: {e}")
            finally:
                self._stream = None

        # Wait for background decoder worker to exit
        if self._decoder_thread and self._decoder_thread.is_alive():
            self._decoder_thread.join(timeout=2.0)
            self._decoder_thread = None

        # Clean up native GGWave instance
        if self._adapter:
            self._adapter.close()

        logger.info("Audio engine stopped cleanly.")

    # -----------------------------------------------------------------------
    # SoundDevice Real-Time Audio Callback
    # -----------------------------------------------------------------------
    def _audio_callback(
        self,
        indata: np.ndarray,
        frames: int,
        time_info: dict,
        status: sd.CallbackFlags,
    ) -> None:
        """
        PortAudio real-time audio callback.

        Strict constraints:
          - Minimal compute overhead only.
          - No blocking locks, file I/O, or CPU-intensive decoding.
          - Copy block and return immediately.
        """
        if status:
            logger.warning(f"PortAudio stream warning flag: {status}")

        if not self._running:
            return

        # Suppress processing during local playback and guard delay
        if self.is_suppressed():
            return

        try:
            # indata is numpy float32 array; copy raw bytes for the decoder queue
            pcm_bytes = indata.tobytes()
            self._audio_queue.put_nowait(pcm_bytes)
        except queue.Full:
            self._dropped_blocks += 1
            if self._dropped_blocks % 50 == 1:
                logger.warning(
                    f"Decoder queue congested! Total dropped blocks: {self._dropped_blocks}"
                )

    # -----------------------------------------------------------------------
    # Background Demodulation Worker
    # -----------------------------------------------------------------------
    def _decoder_worker(self) -> None:
        """
        Background consumer loop that pulls PCM audio blocks and executes
        incremental GGWave demodulation.
        """
        logger.debug("Audio decoder background worker started.")
        while self._running:
            try:
                pcm_chunk = self._audio_queue.get(timeout=0.1)
            except queue.Empty:
                continue

            if not self._running:
                break

            if self._adapter and self._adapter.is_initialized:
                try:
                    decoded = self._adapter.decode(pcm_chunk)
                    if decoded is not None:
                        logger.info(f"Demodulated acoustic frame ({len(decoded)} bytes).")
                        self._dispatch_payload(decoded)
                except Exception as e:
                    logger.error(f"Error during background demodulation: {e}")

        logger.debug("Audio decoder background worker terminated.")

    def _dispatch_payload(self, payload: bytes) -> None:
        """Distribute decoded payload to thread-safe queue and registered observers."""
        self.received_queue.put(payload)
        for cb in list(self._callbacks):
            try:
                cb(payload)
            except Exception as e:
                logger.error(f"Error in payload consumer callback: {e}")

    # -----------------------------------------------------------------------
    # Playback & Transmission Control
    # -----------------------------------------------------------------------
    def play_waveform(self, waveform: bytes, blocking: bool = True) -> None:
        """
        Play an acoustic waveform through the configured output speaker.

        Enforces echo suppression by marking transmission active, waiting for
        playback completion, and timestamping the start of the post-transmission guard.

        Args:
            waveform: Raw float32 PCM audio waveform bytes (from GgWaveAdapter.encode).
            blocking: If True, waits until speaker playback completes before returning.

        Raises:
            AudioEngineError: If speaker playback fails.
        """
        if not waveform:
            raise AudioEngineError("Cannot play empty audio waveform.")

        # Convert float32 raw bytes into NumPy array for SoundDevice
        try:
            samples = np.frombuffer(waveform, dtype=np.float32)
        except Exception as e:
            raise AudioEngineError(f"Invalid waveform buffer structure: {e}") from e

        # Resolve output device
        if self._output_device is None:
            default_out = self._device_manager.get_default_output_device()
            if default_out:
                self._output_device = default_out.index

        # Activate transmission suppression
        with self._tx_lock:
            self._is_transmitting = True
            self._tx_finished_time = 0.0

        def _execute_playback():
            try:
                sd.play(samples, samplerate=self._sample_rate, device=self._output_device)
                sd.wait()
            except Exception as err:
                logger.error(f"Speaker playback error: {err}")
                raise AudioEngineError(f"Audio playback failed: {err}") from err
            finally:
                with self._tx_lock:
                    self._is_transmitting = False
                    self._tx_finished_time = time.monotonic()
                logger.debug(
                    f"Playback ended. Post-transmission guard active for {self._guard_delay_sec*1000:.0f} ms."
                )

        if blocking:
            _execute_playback()
        else:
            tx_thread = threading.Thread(
                target=_execute_playback,
                name="ChirpDrop-AudioPlaybackThread",
                daemon=True,
            )
            tx_thread.start()

    def encode_and_transmit(
        self,
        payload: Union[str, bytes],
        protocol_id: Optional[int] = None,
        volume: Optional[int] = None,
        blocking: bool = True,
    ) -> int:
        """
        High-level transmission helper: encodes a message and plays it through the speaker.

        Args:
            payload: String message or valid UTF-8 bytes to transmit.
            protocol_id: GGWave protocol ID (default: active transmission mode).
            volume: Output gain percentage (1-100, default: profile volume).
            blocking: If True, blocks until playback finishes.

        Returns:
            Number of bytes in the generated audio waveform.
        """
        pid = self._get_active_protocol_id() if protocol_id is None else protocol_id
        vol = self._get_active_volume() if volume is None else volume

        # Ensure adapter is available for encoding
        adapter_created = False
        if self._adapter is None or not self._adapter.is_initialized:
            adapter = GgWaveAdapter(sample_rate=self._sample_rate)
            adapter.initialize()
            adapter_created = True
        else:
            adapter = self._adapter

        try:
            waveform = adapter.encode(payload, protocol_id=pid, volume=vol)
            self.play_waveform(waveform, blocking=blocking)
            return len(waveform)
        finally:
            if adapter_created:
                adapter.close()
