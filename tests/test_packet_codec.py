"""
ChirpDrop - Unit Tests for Packet Codec
---------------------------------------
Validates Base64 encoding/decoding, checksum integrity preservation,
and robust rejection of malformed or corrupted payloads.
"""

import base64
import pytest

from app.communication.packet_codec import (
    CorruptedPacketDataError,
    PacketCodecError,
    PacketDecodingError,
    PacketEncodingError,
    decode_text_to_packet,
    encode_packet_to_text,
)
from app.core import Opcode, Packet


# ---------------------------------------------------------------------------
# Basic Codec Round-Trip Tests
# ---------------------------------------------------------------------------
def test_packet_to_base64_and_reconstruction() -> None:
    """Verify that a standard packet encodes to Base64 and decodes with exact equality."""
    packet = Packet(
        opcode=Opcode.DATA,
        sequence_id=42,
        payload=b"Acoustic packet codec test payload",
    )
    b64_str = encode_packet_to_text(packet)

    assert isinstance(b64_str, str)
    assert len(b64_str) > 0

    # Decodes from str
    recovered = decode_text_to_packet(b64_str)
    assert recovered == packet
    assert recovered.opcode == Opcode.DATA
    assert recovered.sequence_id == 42
    assert recovered.payload == packet.payload

    # Also decodes from bytes
    recovered_bytes = decode_text_to_packet(b64_str.encode("ascii"))
    assert recovered_bytes == packet


def test_empty_payload_packet() -> None:
    """Verify codec handles packets with 0-byte payloads (e.g. SYN, FIN)."""
    packet = Packet(opcode=Opcode.SYN, sequence_id=0, payload=b"")
    b64_str = encode_packet_to_text(packet)

    # 8 bytes header -> 8 / 3 -> 12 characters in Base64
    assert len(b64_str) == 12
    recovered = decode_text_to_packet(b64_str)
    assert recovered == packet
    assert len(recovered.payload) == 0


def test_maximum_size_packet() -> None:
    """Verify codec handles maximum 128-byte binary packet (8 bytes header + 120 bytes payload)."""
    max_payload = bytes(i % 256 for i in range(120))
    packet = Packet(opcode=Opcode.DATA, sequence_id=65535, payload=max_payload)
    assert len(packet.to_bytes()) == 128

    b64_str = encode_packet_to_text(packet)
    # 128 bytes -> ceil(128 / 3) * 4 = 172 chars
    assert len(b64_str) == 172

    recovered = decode_text_to_packet(b64_str)
    assert recovered == packet
    assert len(recovered.payload) == 120


def test_binary_payload_with_null_bytes() -> None:
    """Verify that binary payloads with null bytes (0x00) and high bytes are strictly preserved."""
    binary_payload = b"\x00\x00\xff\xfe\x00\x43\x44\x01\x00\xaa\x55\x00" * 4
    packet = Packet(opcode=Opcode.DATA, sequence_id=99, payload=binary_payload)

    b64_str = encode_packet_to_text(packet)
    recovered = decode_text_to_packet(b64_str)

    assert recovered == packet
    assert recovered.payload == binary_payload


# ---------------------------------------------------------------------------
# Error Handling & Validation Tests
# ---------------------------------------------------------------------------
def test_invalid_input_to_encode() -> None:
    """Verify that passing non-Packet to encode_packet_to_text raises PacketEncodingError."""
    with pytest.raises(PacketEncodingError, match="Expected a Packet instance"):
        encode_packet_to_text("not a packet")  # type: ignore[arg-type]

    with pytest.raises(PacketEncodingError):
        encode_packet_to_text(None)  # type: ignore[arg-type]


def test_invalid_input_to_decode() -> None:
    """Verify that non-string/non-bytes input to decode_text_to_packet raises PacketDecodingError."""
    with pytest.raises(PacketDecodingError, match="Input must be str or bytes"):
        decode_text_to_packet(12345)  # type: ignore[arg-type]

    with pytest.raises(PacketDecodingError, match="empty text payload"):
        decode_text_to_packet("")

    with pytest.raises(PacketDecodingError, match="empty text payload"):
        decode_text_to_packet(b"   ")


def test_invalid_base64_syntax() -> None:
    """Verify that malformed Base64 strings or bad padding raise PacketDecodingError."""
    # Not base64 characters
    with pytest.raises(PacketDecodingError, match="Invalid Base64 payload"):
        decode_text_to_packet("!!!ThisIsNotValidBase64@@@")

    # Incorrect padding / length not multiple of 4
    with pytest.raises(PacketDecodingError, match="Invalid Base64 payload"):
        decode_text_to_packet("Q0QBAg")


def test_corrupted_packet_checksum() -> None:
    """Verify that tampering with packet contents raises CorruptedPacketDataError."""
    packet = Packet(opcode=Opcode.DATA, sequence_id=1, payload=b"Original Authentic Payload")
    raw = bytearray(packet.to_bytes())

    # Corrupt a byte in the payload
    raw[-1] ^= 0x01
    corrupted_b64 = base64.b64encode(bytes(raw)).decode("ascii")

    with pytest.raises(CorruptedPacketDataError, match="integrity check failed"):
        decode_text_to_packet(corrupted_b64)


def test_invalid_packet_length_in_base64() -> None:
    """Verify that Base64 encoding of incomplete header raises PacketDecodingError."""
    too_short_bytes = b"CD\x01\x01"  # Only 4 bytes (header requires 8)
    b64_short = base64.b64encode(too_short_bytes).decode("ascii")

    with pytest.raises(PacketDecodingError, match="Malformed packet framing"):
        decode_text_to_packet(b64_short)


def test_invalid_opcode_in_base64() -> None:
    """Verify that Base64 payload with an invalid opcode raises PacketDecodingError."""
    bad_header = b"CD\x01\x99\x00\x01\x00\x00"  # Opcode 0x99 is undefined
    b64_bad_op = base64.b64encode(bad_header).decode("ascii")

    with pytest.raises(PacketDecodingError, match="Malformed packet framing"):
        decode_text_to_packet(b64_bad_op)
