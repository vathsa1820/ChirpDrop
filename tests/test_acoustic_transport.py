"""
ChirpDrop - Unit & Integration Tests for Acoustic Transport Layer
-----------------------------------------------------------------
Validates packet transmission via AudioEngine, inbound packet reconstruction,
queue dispatch, observer callbacks, lifecycle management, and end-to-end
software waveform modulation integration with GGWave.
"""

from unittest.mock import MagicMock
import pytest

from app.audio import AudioEngineError, GgWaveAdapter, PROTOCOL_AUDIBLE_FAST
from app.communication.acoustic_transport import (
    AcousticTransport,
    AcousticTransportError,
    TransmissionError,
)
from app.communication.packet_codec import decode_text_to_packet, encode_packet_to_text
from app.core import Opcode, Packet


# ---------------------------------------------------------------------------
# Unit Tests with Mocked AudioEngine
# ---------------------------------------------------------------------------
def test_transmission_through_mock_engine() -> None:
    """Verify that send_packet encodes to Base64 and passes to AudioEngine.encode_and_transmit."""
    mock_engine = MagicMock()
    mock_engine.encode_and_transmit.return_value = 40960  # Mock waveform byte count

    transport = AcousticTransport(audio_engine=mock_engine)
    packet = Packet(opcode=Opcode.DATA, sequence_id=10, payload=b"Test Transport Transmission")

    waveform_len = transport.send_packet(packet, blocking=True)
    assert waveform_len == 40960

    # Ensure encode_and_transmit was called with Base64 text of the packet
    mock_engine.encode_and_transmit.assert_called_once()
    called_text = mock_engine.encode_and_transmit.call_args[0][0]
    assert called_text == encode_packet_to_text(packet)


def test_transmission_error_handling() -> None:
    """Verify that transmission failures from AudioEngine raise TransmissionError."""
    mock_engine = MagicMock()
    mock_engine.encode_and_transmit.side_effect = AudioEngineError("Hardware playback failed")

    transport = AcousticTransport(audio_engine=mock_engine)
    packet = Packet(opcode=Opcode.SYN, sequence_id=0, payload=b"")

    with pytest.raises(TransmissionError, match="Hardware playback failed"):
        transport.send_packet(packet)


def test_receiving_valid_decoded_packet() -> None:
    """Verify that inbound audio payloads are parsed into Packet objects and dispatched."""
    mock_engine = MagicMock()
    transport = AcousticTransport(audio_engine=mock_engine)

    received_in_callback = []

    def on_packet(p: Packet):
        received_in_callback.append(p)

    transport.register_packet_callback(on_packet)

    original_packet = Packet(opcode=Opcode.DATA, sequence_id=77, payload=b"Acoustic Inbound Message")
    b64_payload = encode_packet_to_text(original_packet).encode("ascii")

    # Simulate AudioEngine background worker delivering decoded bytes
    transport._on_audio_payload_received(b64_payload)

    # 1. Received queue has the packet
    assert not transport.received_packets.empty()
    queued_packet = transport.received_packets.get_nowait()
    assert queued_packet == original_packet

    # 2. Observer callback received the packet
    assert len(received_in_callback) == 1
    assert received_in_callback[0] == original_packet


def test_rejecting_invalid_or_corrupted_payloads() -> None:
    """Verify that corrupted Base64 or failing checksums are discarded without dispatching."""
    mock_engine = MagicMock()
    transport = AcousticTransport(audio_engine=mock_engine)

    received_in_callback = []
    transport.register_packet_callback(lambda p: received_in_callback.append(p))

    # 1. Non-base64 garbage
    transport._on_audio_payload_received(b"Random-Noise-!@#$%^")
    assert transport.received_packets.empty()
    assert len(received_in_callback) == 0

    # 2. Corrupted packet bytes (tampered payload)
    valid_packet = Packet(opcode=Opcode.DATA, sequence_id=1, payload=b"Sensitive Data")
    raw = bytearray(valid_packet.to_bytes())
    raw[-1] ^= 0xFF  # Corrupt checksum
    corrupted_b64 = encode_packet_to_text(valid_packet)[:-4].encode("ascii") + b"AAAA"
    transport._on_audio_payload_received(corrupted_b64)

    assert transport.received_packets.empty()
    assert len(received_in_callback) == 0


def test_observer_callback_error_isolation() -> None:
    """Verify that an exception inside a user observer callback does not crash packet processing."""
    mock_engine = MagicMock()
    transport = AcousticTransport(audio_engine=mock_engine)

    good_callback_packets = []

    def failing_callback(p: Packet):
        raise RuntimeError("User callback crashed!")

    def good_callback(p: Packet):
        good_callback_packets.append(p)

    transport.register_packet_callback(failing_callback)
    transport.register_packet_callback(good_callback)

    packet = Packet(opcode=Opcode.DATA, sequence_id=5, payload=b"Robustness Test")
    b64_payload = encode_packet_to_text(packet).encode("ascii")

    # Should not raise exception
    transport._on_audio_payload_received(b64_payload)

    # Good callback still received the packet
    assert len(good_callback_packets) == 1
    assert good_callback_packets[0] == packet
    assert not transport.received_packets.empty()


def test_start_and_stop_lifecycle() -> None:
    """Verify lifecycle start/stop registration on AudioEngine."""
    mock_engine = MagicMock()
    mock_engine.is_running = False

    transport = AcousticTransport(audio_engine=mock_engine)
    assert not transport.is_running

    transport.start()
    assert transport.is_running
    mock_engine.register_callback.assert_called_once()
    mock_engine.start_capture.assert_called_once()

    # Re-calling start when running is a no-op
    transport.start()
    assert mock_engine.start_capture.call_count == 1

    transport.stop()
    assert not transport.is_running
    mock_engine.unregister_callback.assert_called_once()


# ---------------------------------------------------------------------------
# Software Integration Test with Real GGWave Adapter
# ---------------------------------------------------------------------------
def test_full_software_ggwave_packet_roundtrip_integration() -> None:
    """
    End-to-end integration test:
      1. Create a binary Packet.
      2. Encode Packet to Base64 text.
      3. Modulate Base64 text into raw audio waveform using real GGWaveAdapter.
      4. Demodulate audio waveform using real GGWaveAdapter.
      5. Decode recovered Base64 text into a Packet object.
      6. Confirm byte-for-byte packet equality and checksum verification.
    """
    # 64-byte payload fits cleanly inside GGWave's 140-byte single-chirp buffer
    test_payload = b"ChirpDrop Acoustic Integration Test Payload (CRC-16 Verified)"
    original_packet = Packet(
        opcode=Opcode.DATA,
        sequence_id=4096,
        payload=test_payload,
    )

    # Step 1 & 2: Packet -> Base64
    b64_text = encode_packet_to_text(original_packet)
    assert len(b64_text) <= 140

    # Step 3 & 4: Real GGWave Software Waveform Modulation & Demodulation
    with GgWaveAdapter(sample_rate=48000) as adapter:
        waveform = adapter.encode(b64_text, protocol_id=PROTOCOL_AUDIBLE_FAST, volume=20)
        assert len(waveform) > 0

        decoded_bytes = adapter.decode(waveform)
        assert decoded_bytes is not None

    # Step 5: Base64 -> Packet reconstruction
    recovered_packet = decode_text_to_packet(decoded_bytes)

    # Step 6: Verify equality
    assert recovered_packet == original_packet
    assert recovered_packet.opcode == Opcode.DATA
    assert recovered_packet.sequence_id == 4096
    assert recovered_packet.payload == test_payload
    assert recovered_packet.calculate_checksum() == original_packet.calculate_checksum()
