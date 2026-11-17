"""
ChirpDrop - Acoustic Packet Transport Layer
-------------------------------------------
Bridges binary packet framing with physical acoustic transmission and reception.
Handles text serialization, waveform modulation, echo-suppressed playback,
asynchronous reception, and packet reconstruction.
"""

from collections.abc import Callable
import logging
import queue
import threading
from typing import List, Optional

from app.audio import AudioEngine, AudioEngineError
from app.communication.packet_codec import (
    CorruptedPacketDataError,
    PacketCodecError,
    decode_text_to_packet,
    encode_packet_to_text,
)
from app.core import Packet
from config import TransmissionMode

logger = logging.getLogger("ChirpDrop.AcousticTransport")


# ---------------------------------------------------------------------------
# Custom Exceptions
# ---------------------------------------------------------------------------
class AcousticTransportError(Exception):
    """Base exception for acoustic transport layer errors."""


class TransmissionError(AcousticTransportError):
    """Raised when transmitting an acoustic packet fails."""


# ---------------------------------------------------------------------------
# Acoustic Transport Class
# ---------------------------------------------------------------------------
class AcousticTransport:
    """
    High-level transport engine for transmitting and receiving ChirpDrop Packet objects
    over acoustic sound waves.
    """

    def __init__(
        self,
        audio_engine: Optional[AudioEngine] = None,
        transmission_mode: Optional[TransmissionMode] = None,
    ) -> None:
        """
        Initialize the acoustic transport layer.

        Args:
            audio_engine: Shared AudioEngine instance. If None, a new default engine is created.
            transmission_mode: TransmissionMode.AUDIBLE or TransmissionMode.ULTRASONIC.
        """
        self._engine = audio_engine if audio_engine is not None else AudioEngine()
        if transmission_mode is not None:
            self._engine.set_transmission_mode(transmission_mode)

        self._received_packets: queue.Queue[Packet] = queue.Queue()
        self._packet_callbacks: List[Callable[[Packet], None]] = []
        self._lock = threading.Lock()
        self._is_running = False

    @property
    def is_running(self) -> bool:
        """True if acoustic transport capture is actively listening."""
        return self._is_running

    @property
    def received_packets(self) -> queue.Queue[Packet]:
        """Thread-safe queue containing successfully validated incoming Packet objects."""
        return self._received_packets

    @property
    def audio_engine(self) -> AudioEngine:
        """Reference to the underlying AudioEngine."""
        return self._engine

    @property
    def transmission_mode(self) -> TransmissionMode:
        """Current acoustic transmission mode (Audible or Ultrasonic)."""
        return self._engine.transmission_mode

    def set_transmission_mode(self, mode: TransmissionMode) -> None:
        """
        Update the operating transmission profile.

        Args:
            mode: Desired TransmissionMode enum value.
        """
        self._engine.set_transmission_mode(mode)

    # -----------------------------------------------------------------------
    # Observer Pattern Registration
    # -----------------------------------------------------------------------
    def register_packet_callback(self, callback: Callable[[Packet], None]) -> None:
        """
        Register a callback invoked whenever a valid Packet is demodulated and validated.

        Args:
            callback: Function accepting a validated Packet instance.
        """
        with self._lock:
            if callback not in self._packet_callbacks:
                self._packet_callbacks.append(callback)

    def unregister_packet_callback(self, callback: Callable[[Packet], None]) -> None:
        """
        Remove a previously registered packet observer callback.

        Args:
            callback: Function to unregister.
        """
        with self._lock:
            if callback in self._packet_callbacks:
                self._packet_callbacks.remove(callback)

    # -----------------------------------------------------------------------
    # Lifecycle Management
    # -----------------------------------------------------------------------
    def start(self) -> None:
        """
        Start listening for incoming acoustic packets.

        Registers the transport's inbound payload handler on the underlying
        AudioEngine and begins microphone capture.
        """
        with self._lock:
            if self._is_running:
                logger.warning("AcousticTransport is already running.")
                return

            # Register transport receiver callback with AudioEngine
            self._engine.register_callback(self._on_audio_payload_received)

            try:
                if not self._engine.is_running:
                    self._engine.start_capture()
                self._is_running = True
                logger.info("AcousticTransport started successfully.")
            except AudioEngineError as err:
                self._engine.unregister_callback(self._on_audio_payload_received)
                logger.error(f"Failed to start underlying AudioEngine: {err}")
                raise AcousticTransportError(f"Transport startup failed: {err}") from err

    def stop(self) -> None:
        """
        Stop listening and release audio resources.
        """
        with self._lock:
            if not self._is_running:
                return

            self._engine.unregister_callback(self._on_audio_payload_received)
            if self._engine.is_running:
                self._engine.stop_capture()

            self._is_running = False
            logger.info("AcousticTransport stopped.")

    def __enter__(self) -> "AcousticTransport":
        self.start()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.stop()

    # -----------------------------------------------------------------------
    # Transmission
    # -----------------------------------------------------------------------
    def send_packet(
        self,
        packet: Packet,
        blocking: bool = True,
        protocol_id: Optional[int] = None,
        volume: Optional[int] = None,
    ) -> int:
        """
        Encode a Packet into Base64 ASCII, modulate into an acoustic waveform,
        and play it through the speaker.

        Args:
            packet: Validated Packet object to transmit.
            blocking: If True, blocks until speaker playback completes.
            protocol_id: Optional GGWave protocol override.
            volume: Optional volume percentage (1-100) override.

        Returns:
            Length of the synthesized audio waveform in bytes.

        Raises:
            TransmissionError: If packet encoding or speaker playback fails.
        """
        try:
            b64_payload = encode_packet_to_text(packet)
            logger.debug(
                f"Sending Packet (Opcode: {packet.opcode.name}, Seq: {packet.sequence_id}, "
                f"B64 Len: {len(b64_payload)})"
            )
            waveform_len = self._engine.encode_and_transmit(
                b64_payload,
                protocol_id=protocol_id,
                volume=volume,
                blocking=blocking,
            )
            return waveform_len
        except (PacketCodecError, AudioEngineError) as err:
            logger.error(f"Acoustic packet transmission failed: {err}")
            raise TransmissionError(f"Transmission failed: {err}") from err

    # -----------------------------------------------------------------------
    # Inbound Payload Reception & Validation
    # -----------------------------------------------------------------------
    def _on_audio_payload_received(self, raw_bytes: bytes) -> None:
        """
        Handler invoked by the background AudioEngine worker upon demodulating an audio block.

        Attempts to decode the Base64 payload into a Packet and dispatches it
        to the received queue and registered observers.

        Args:
            raw_bytes: Raw bytes returned by GGWave.
        """
        try:
            packet = decode_text_to_packet(raw_bytes)
        except CorruptedPacketDataError as err:
            logger.warning(f"Discarded acoustically received data (CRC/integrity failure): {err}")
            return
        except PacketCodecError as err:
            logger.warning(f"Discarded acoustically received data (malformed framing/Base64): {err}")
            return
        except Exception as err:
            logger.error(f"Unexpected error decoding acoustic payload: {err}")
            return

        logger.info(
            f"Successfully recovered Packet: Opcode={packet.opcode.name}, "
            f"Seq={packet.sequence_id}, PayloadLen={len(packet.payload)}"
        )

        # 1. Enqueue to thread-safe queue
        self._received_packets.put(packet)

        # 2. Notify observers safely
        with self._lock:
            callbacks = list(self._packet_callbacks)

        for cb in callbacks:
            try:
                cb(packet)
            except Exception as cb_err:
                logger.error(f"Error in packet observer callback {cb}: {cb_err}")
