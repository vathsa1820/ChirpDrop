"""
ChirpDrop - Unit Tests for Binary Packet Framing
------------------------------------------------
Comprehensive pytest suite validating packet serialization, deserialization,
CRC-16 checksum integrity, and protocol constraints.
"""

import struct
import pytest

from app.core.packet import (
    HEADER_SIZE,
    MAGIC,
    MAX_PACKET_SIZE,
    MAX_PAYLOAD_SIZE,
    ChecksumMismatchError,
    InvalidMagicError,
    InvalidPacketLengthError,
    InvalidSequenceNumberError,
    Opcode,
    OversizedPayloadError,
    Packet,
    UnsupportedOpcodeError,
)


# ---------------------------------------------------------------------------
# Test 1: Valid SYN packet serialization
# ---------------------------------------------------------------------------
def test_valid_syn_packet_serialization() -> None:
    """Validate binary packing of a SYN (handshake initiation) packet."""
    packet = Packet(opcode=Opcode.SYN, sequence_id=0, payload=b"")
    raw = packet.to_bytes()

    assert len(raw) == HEADER_SIZE
    assert raw[:3] == MAGIC
    assert raw[3] == Opcode.SYN
    seq_id, checksum = struct.unpack(">HH", raw[4:8])
    assert seq_id == 0
    assert checksum == packet.calculate_checksum()


# ---------------------------------------------------------------------------
# Test 2: Valid DATA packet serialization
# ---------------------------------------------------------------------------
def test_valid_data_packet_serialization() -> None:
    """Validate binary packing of a DATA packet with a text payload."""
    payload = b"ChirpDrop Acoustic Test Payload"
    packet = Packet(opcode=Opcode.DATA, sequence_id=100, payload=payload)
    raw = packet.to_bytes()

    assert len(raw) == HEADER_SIZE + len(payload)
    assert raw[:3] == MAGIC
    assert raw[3] == Opcode.DATA
    seq_id, checksum = struct.unpack(">HH", raw[4:8])
    assert seq_id == 100
    assert checksum == packet.calculate_checksum()
    assert raw[HEADER_SIZE:] == payload


# ---------------------------------------------------------------------------
# Test 3: Valid NACK packet serialization
# ---------------------------------------------------------------------------
def test_valid_nack_packet_serialization() -> None:
    """Validate binary packing of a NACK (negative acknowledgment) packet."""
    # NACK payload indicating missing sequence number 42
    payload = struct.pack(">H", 42)
    packet = Packet(opcode=Opcode.NACK, sequence_id=5, payload=payload)
    raw = packet.to_bytes()

    assert len(raw) == HEADER_SIZE + len(payload)
    assert raw[3] == Opcode.NACK
    parsed = Packet.from_bytes(raw)
    assert parsed.opcode == Opcode.NACK
    assert parsed.sequence_id == 5
    assert parsed.payload == payload


# ---------------------------------------------------------------------------
# Test 4: Valid FIN packet serialization
# ---------------------------------------------------------------------------
def test_valid_fin_packet_serialization() -> None:
    """Validate binary packing of a FIN (finalization) packet."""
    packet = Packet(opcode=Opcode.FIN, sequence_id=999, payload=b"")
    raw = packet.to_bytes()

    assert len(raw) == HEADER_SIZE
    assert raw[3] == Opcode.FIN
    parsed = Packet.from_bytes(raw)
    assert parsed.opcode == Opcode.FIN
    assert parsed.sequence_id == 999
    assert parsed.payload == b""


# ---------------------------------------------------------------------------
# Test 5: Packet serialization and parsing round-trip
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "opcode,seq_id,payload",
    [
        (Opcode.SYN, 0, b""),
        (Opcode.DATA, 1, b"Acoustic packet data"),
        (Opcode.DATA, 1234, bytes([x % 256 for x in range(64)])),
        (Opcode.NACK, 250, b"\x00\x05\x00\x06"),
        (Opcode.FIN, 65535, b"END"),
    ],
)
def test_serialization_round_trip(opcode: Opcode, seq_id: int, payload: bytes) -> None:
    """Verify that serialization followed by deserialization perfectly preserves all packet data."""
    original = Packet(opcode=opcode, sequence_id=seq_id, payload=payload)
    serialized = original.to_bytes()
    recovered = Packet.from_bytes(serialized)

    assert recovered.opcode == original.opcode
    assert recovered.sequence_id == original.sequence_id
    assert recovered.payload == original.payload
    assert recovered == original


# ---------------------------------------------------------------------------
# Test 6: Empty payload
# ---------------------------------------------------------------------------
def test_empty_payload() -> None:
    """Verify handling of packets with 0-byte payload."""
    packet = Packet(opcode=Opcode.SYN, sequence_id=0, payload=b"")
    raw = packet.to_bytes()

    assert len(raw) == HEADER_SIZE
    parsed = Packet.from_bytes(raw)
    assert parsed.payload == b""
    assert len(parsed.payload) == 0


# ---------------------------------------------------------------------------
# Test 7: Maximum 120-byte payload
# ---------------------------------------------------------------------------
def test_maximum_120_byte_payload() -> None:
    """Verify packet serialization with the maximum allowable payload size of 120 bytes."""
    max_payload = bytes(i % 256 for i in range(MAX_PAYLOAD_SIZE))
    assert len(max_payload) == 120

    packet = Packet(opcode=Opcode.DATA, sequence_id=500, payload=max_payload)
    raw = packet.to_bytes()

    assert len(raw) == MAX_PACKET_SIZE  # Exactly 128 bytes
    parsed = Packet.from_bytes(raw)
    assert parsed.payload == max_payload
    assert len(parsed.payload) == MAX_PAYLOAD_SIZE


# ---------------------------------------------------------------------------
# Test 8: Payload larger than 120 bytes
# ---------------------------------------------------------------------------
def test_payload_larger_than_120_bytes() -> None:
    """Verify that payloads exceeding 120 bytes raise OversizedPayloadError."""
    oversized_payload = b"X" * (MAX_PAYLOAD_SIZE + 1)  # 121 bytes

    # Test direct dataclass instantiation
    with pytest.raises(OversizedPayloadError):
        Packet(opcode=Opcode.DATA, sequence_id=1, payload=oversized_payload)

    # Test deserialization of oversized raw buffer
    fake_header = struct.pack(">3sBHH", MAGIC, Opcode.DATA, 1, 0)
    oversized_raw = fake_header + oversized_payload
    with pytest.raises(OversizedPayloadError):
        Packet.from_bytes(oversized_raw)


# ---------------------------------------------------------------------------
# Test 9: Invalid magic bytes
# ---------------------------------------------------------------------------
def test_invalid_magic_bytes() -> None:
    """Verify that raw bytes with an incorrect magic preamble raise InvalidMagicError."""
    valid_packet = Packet(opcode=Opcode.DATA, sequence_id=1, payload=b"test")
    raw = valid_packet.to_bytes()

    # Corrupt magic preamble from b"CD\x01" to b"XX\x01"
    corrupted_magic = b"XX\x01" + raw[3:]
    with pytest.raises(InvalidMagicError):
        Packet.from_bytes(corrupted_magic)

    # Corrupt with completely random magic
    corrupted_random = b"\x00\x00\x00" + raw[3:]
    with pytest.raises(InvalidMagicError):
        Packet.from_bytes(corrupted_random)


# ---------------------------------------------------------------------------
# Test 10: Unsupported opcode
# ---------------------------------------------------------------------------
def test_unsupported_opcode() -> None:
    """Verify that unrecognized opcodes raise UnsupportedOpcodeError."""
    # Test during instantiation
    with pytest.raises(UnsupportedOpcodeError):
        Packet(opcode=0x00, sequence_id=1, payload=b"")  # 0x00 is not defined

    with pytest.raises(UnsupportedOpcodeError):
        Packet(opcode=0x05, sequence_id=1, payload=b"")  # 0x05 is not defined

    with pytest.raises(UnsupportedOpcodeError):
        Packet(opcode=0xFF, sequence_id=1, payload=b"")  # 0xFF is not defined

    # Test during deserialization
    bad_header = struct.pack(">3sBHH", MAGIC, 0x99, 1, 0)
    with pytest.raises(UnsupportedOpcodeError):
        Packet.from_bytes(bad_header)


# ---------------------------------------------------------------------------
# Test 11: Invalid packet length
# ---------------------------------------------------------------------------
def test_invalid_packet_length() -> None:
    """Verify that buffers shorter than HEADER_SIZE (8 bytes) raise InvalidPacketLengthError."""
    # Completely empty buffer
    with pytest.raises(InvalidPacketLengthError):
        Packet.from_bytes(b"")

    # Partial preamble (3 bytes)
    with pytest.raises(InvalidPacketLengthError):
        Packet.from_bytes(MAGIC)

    # Incomplete header (7 bytes)
    with pytest.raises(InvalidPacketLengthError):
        Packet.from_bytes(b"CD\x01\x01\x00\x01\x00")


# ---------------------------------------------------------------------------
# Test 12: Invalid sequence number
# ---------------------------------------------------------------------------
def test_invalid_sequence_number() -> None:
    """Verify that sequence IDs outside [0, 65535] raise InvalidSequenceNumberError."""
    # Negative sequence ID
    with pytest.raises(InvalidSequenceNumberError):
        Packet(opcode=Opcode.DATA, sequence_id=-1, payload=b"")

    # Sequence ID > 65535 (uint16 overflow)
    with pytest.raises(InvalidSequenceNumberError):
        Packet(opcode=Opcode.DATA, sequence_id=65536, payload=b"")

    # Non-integer sequence ID
    with pytest.raises(InvalidSequenceNumberError):
        Packet(opcode=Opcode.DATA, sequence_id="42", payload=b"")  # type: ignore[arg-type]

    # Boolean sequence ID (bool is subclass of int in Python)
    with pytest.raises(InvalidSequenceNumberError):
        Packet(opcode=Opcode.DATA, sequence_id=True, payload=b"")  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Test 13: Modified payload causing checksum failure
# ---------------------------------------------------------------------------
def test_modified_payload_causing_checksum_failure() -> None:
    """Verify that tampering with the payload invalidates the CRC-16 checksum."""
    packet = Packet(opcode=Opcode.DATA, sequence_id=10, payload=b"Authentic Data")
    raw = bytearray(packet.to_bytes())

    # Tamper with the last byte of the payload
    raw[-1] ^= 0x01

    with pytest.raises(ChecksumMismatchError):
        Packet.from_bytes(bytes(raw))


# ---------------------------------------------------------------------------
# Test 14: Modified sequence ID causing checksum failure
# ---------------------------------------------------------------------------
def test_modified_sequence_id_causing_checksum_failure() -> None:
    """Verify that altering the sequence ID without recomputing checksum raises ChecksumMismatchError."""
    packet = Packet(opcode=Opcode.DATA, sequence_id=10, payload=b"Acoustic Frame")
    raw = bytearray(packet.to_bytes())

    # Bytes 4-5 represent sequence_id. Alter byte 5
    raw[5] ^= 0xFF

    with pytest.raises(ChecksumMismatchError):
        Packet.from_bytes(bytes(raw))


# ---------------------------------------------------------------------------
# Test 15: Modified opcode causing checksum failure
# ---------------------------------------------------------------------------
def test_modified_opcode_causing_checksum_failure() -> None:
    """Verify that modifying the opcode in a serialized packet causes checksum verification to fail."""
    packet = Packet(opcode=Opcode.DATA, sequence_id=1, payload=b"Payload")
    raw = bytearray(packet.to_bytes())

    # Change opcode from DATA (0x02) to SYN (0x01)
    raw[3] = Opcode.SYN

    with pytest.raises(ChecksumMismatchError):
        Packet.from_bytes(bytes(raw))


# ---------------------------------------------------------------------------
# Test 16: Random binary payload containing null bytes
# ---------------------------------------------------------------------------
def test_random_binary_payload_containing_null_bytes() -> None:
    """Verify that arbitrary binary payloads containing null bytes (0x00) and high bytes are preserved."""
    binary_payload = b"\x00\x00\xFF\xFE\x00\xAA\x55\x00\x00\x7F\x80\x00" * 8  # 96 bytes
    assert b"\x00" in binary_payload

    packet = Packet(opcode=Opcode.DATA, sequence_id=77, payload=binary_payload)
    raw = packet.to_bytes()
    parsed = Packet.from_bytes(raw)

    assert parsed.payload == binary_payload
    assert len(parsed.payload) == len(binary_payload)
    assert parsed.sequence_id == 77
    assert parsed.opcode == Opcode.DATA


# ---------------------------------------------------------------------------
# Test 17: Maximum sequence ID 65535
# ---------------------------------------------------------------------------
def test_maximum_sequence_id_65535() -> None:
    """Verify that the boundary maximum sequence number 65535 (0xFFFF) is handled correctly."""
    packet = Packet(opcode=Opcode.DATA, sequence_id=65535, payload=b"Max Seq")
    raw = packet.to_bytes()
    parsed = Packet.from_bytes(raw)

    assert parsed.sequence_id == 65535
    assert parsed.payload == b"Max Seq"


# ---------------------------------------------------------------------------
# Test 18: Minimum sequence ID 0
# ---------------------------------------------------------------------------
def test_minimum_sequence_id_0() -> None:
    """Verify that the boundary minimum sequence number 0 is handled correctly."""
    packet = Packet(opcode=Opcode.SYN, sequence_id=0, payload=b"")
    raw = packet.to_bytes()
    parsed = Packet.from_bytes(raw)

    assert parsed.sequence_id == 0
    assert parsed.payload == b""
    assert len(raw) == HEADER_SIZE
