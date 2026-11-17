"""
ChirpDrop - Binary Packet Framing Module
----------------------------------------
Implements binary packet framing, serialization, deserialization, and CRC-16
validation for air-gapped acoustic communication.
"""

from dataclasses import dataclass
from enum import IntEnum
import struct
from typing import Final, Union
import zlib

# ---------------------------------------------------------------------------
# Protocol Constants
# ---------------------------------------------------------------------------
MAGIC: Final[bytes] = b"CD\x01"
HEADER_SIZE: Final[int] = 8
MAX_PAYLOAD_SIZE: Final[int] = 120
MAX_PACKET_SIZE: Final[int] = 128  # HEADER_SIZE (8) + MAX_PAYLOAD_SIZE (120)

# Binary format for the 8-byte header:
# >   : Big-endian (network byte order)
# 3s  : 3 bytes magic preamble (b"CD\x01")
# B   : 1 byte opcode (uint8)
# H   : 2 bytes sequence ID (uint16)
# H   : 2 bytes checksum (uint16, lower 16 bits of CRC-32)
HEADER_FORMAT: Final[str] = ">3sBHH"


# ---------------------------------------------------------------------------
# Protocol Opcodes
# ---------------------------------------------------------------------------
class Opcode(IntEnum):
    """Protocol operation codes."""
    SYN = 0x01   # Synchronization / session handshake
    DATA = 0x02  # Fragmented data payload packet
    NACK = 0x03  # Negative acknowledgment / retransmission request
    FIN = 0x04   # Finalization / transfer completion


# ---------------------------------------------------------------------------
# Custom Protocol Exceptions
# ---------------------------------------------------------------------------
class PacketError(Exception):
    """Base exception for all packet framing and validation errors."""


class InvalidMagicError(PacketError):
    """Raised when the packet does not start with the expected magic preamble."""


class UnsupportedOpcodeError(PacketError):
    """Raised when the packet opcode is not a recognized Opcode enum member."""


class InvalidPacketLengthError(PacketError):
    """Raised when raw packet bytes are too short or length is malformed."""


class OversizedPayloadError(InvalidPacketLengthError):
    """Raised when the payload exceeds MAX_PAYLOAD_SIZE (120 bytes)."""


class InvalidSequenceNumberError(PacketError):
    """Raised when the sequence ID is outside the valid range [0, 65535]."""


class ChecksumMismatchError(PacketError):
    """Raised when the received checksum does not match the calculated CRC-16."""


# ---------------------------------------------------------------------------
# Checksum Calculation
# ---------------------------------------------------------------------------
def compute_checksum(
    opcode: Union[Opcode, int],
    sequence_id: int,
    payload: bytes,
) -> int:
    """
    Calculate the packet checksum as the lower 16 bits of CRC-32.

    The checksum is computed over:
        MAGIC (3 bytes) + OPCODE (1 byte) + SEQUENCE_ID (2 bytes) + PAYLOAD (N bytes)
    Excluding the two checksum bytes.

    Args:
        opcode: Operation code integer or Opcode enum member.
        sequence_id: Unsigned 16-bit sequence number (0-65535).
        payload: Binary payload bytes (0-120 bytes).

    Returns:
        Unsigned 16-bit integer representing the lower 16 bits of CRC-32.
    """
    buffer = MAGIC + struct.pack(">BH", int(opcode), sequence_id) + payload
    return zlib.crc32(buffer) & 0xFFFF


# ---------------------------------------------------------------------------
# Packet Dataclass
# ---------------------------------------------------------------------------
@dataclass(slots=True)
class Packet:
    """
    Represents an acoustic transmission packet in ChirpDrop.

    Attributes:
        opcode: Opcode enum instance representing the packet type.
        sequence_id: Monotonically increasing sequence number (0 to 65535).
        payload: Binary payload chunk (0 to 120 bytes).
    """

    opcode: Opcode
    sequence_id: int
    payload: bytes = b""

    def __post_init__(self) -> None:
        """Validate packet fields immediately upon instantiation."""
        self.validate()

    def validate(self) -> None:
        """
        Validate packet fields against protocol constraints.

        Raises:
            UnsupportedOpcodeError: If opcode is unrecognized.
            InvalidSequenceNumberError: If sequence_id is outside [0, 65535].
            OversizedPayloadError: If payload exceeds MAX_PAYLOAD_SIZE bytes.
            TypeError: If types are invalid.
        """
        # Validate opcode
        if not isinstance(self.opcode, Opcode):
            try:
                object.__setattr__(self, "opcode", Opcode(self.opcode))
            except (ValueError, TypeError):
                raise UnsupportedOpcodeError(f"Unsupported opcode: {self.opcode!r}")

        # Validate sequence ID (exclude bool as it is a subclass of int in Python)
        if not isinstance(self.sequence_id, int) or isinstance(self.sequence_id, bool):
            raise InvalidSequenceNumberError(
                f"Sequence ID must be an integer, got {type(self.sequence_id).__name__}"
            )
        if not (0 <= self.sequence_id <= 65535):
            raise InvalidSequenceNumberError(
                f"Sequence ID {self.sequence_id} is out of bounds [0, 65535]"
            )

        # Validate payload
        if not isinstance(self.payload, (bytes, bytearray)):
            raise TypeError(
                f"Payload must be bytes or bytearray, got {type(self.payload).__name__}"
            )
        if isinstance(self.payload, bytearray):
            object.__setattr__(self, "payload", bytes(self.payload))
        if len(self.payload) > MAX_PAYLOAD_SIZE:
            raise OversizedPayloadError(
                f"Payload size {len(self.payload)} bytes exceeds maximum of {MAX_PAYLOAD_SIZE} bytes"
            )

    def calculate_checksum(self) -> int:
        """
        Calculate the 16-bit CRC checksum for this packet.

        Returns:
            Computed 16-bit checksum integer.
        """
        return compute_checksum(self.opcode, self.sequence_id, self.payload)

    def to_bytes(self) -> bytes:
        """
        Serialize this Packet into its 8-byte header + payload binary representation.

        Returns:
            Serialized packet byte sequence.
        """
        self.validate()
        checksum = self.calculate_checksum()
        header = struct.pack(
            HEADER_FORMAT,
            MAGIC,
            int(self.opcode),
            self.sequence_id,
            checksum,
        )
        return header + self.payload

    @classmethod
    def from_bytes(cls, data: bytes) -> "Packet":
        """
        Deserialize and validate a raw binary packet.

        Args:
            data: Raw binary byte sequence.

        Returns:
            Validated Packet instance.

        Raises:
            InvalidPacketLengthError: If data is shorter than HEADER_SIZE (8 bytes).
            OversizedPayloadError: If payload length exceeds MAX_PAYLOAD_SIZE (120 bytes).
            InvalidMagicError: If magic preamble does not match b"CD\\x01".
            UnsupportedOpcodeError: If opcode byte is unrecognized.
            InvalidSequenceNumberError: If sequence ID is out of bounds.
            ChecksumMismatchError: If the CRC-16 checksum verification fails.
            TypeError: If input is not bytes or bytearray.
        """
        if not isinstance(data, (bytes, bytearray)):
            raise TypeError(f"Packet data must be bytes or bytearray, got {type(data).__name__}")

        total_len = len(data)
        if total_len < HEADER_SIZE:
            raise InvalidPacketLengthError(
                f"Packet length ({total_len} bytes) is shorter than header size ({HEADER_SIZE} bytes)"
            )

        payload_len = total_len - HEADER_SIZE
        if payload_len > MAX_PAYLOAD_SIZE:
            raise OversizedPayloadError(
                f"Packet length ({total_len} bytes) contains payload of {payload_len} bytes, "
                f"exceeding maximum payload limit of {MAX_PAYLOAD_SIZE} bytes"
            )

        magic = bytes(data[:3])
        if magic != MAGIC:
            raise InvalidMagicError(
                f"Invalid magic preamble: {magic!r}; expected {MAGIC!r}"
            )

        _, opcode_val, seq_id, received_checksum = struct.unpack(
            HEADER_FORMAT, data[:HEADER_SIZE]
        )

        try:
            opcode = Opcode(opcode_val)
        except ValueError:
            raise UnsupportedOpcodeError(f"Unsupported opcode: 0x{opcode_val:02X}")

        if not (0 <= seq_id <= 65535):
            raise InvalidSequenceNumberError(
                f"Sequence ID {seq_id} is out of bounds [0, 65535]"
            )

        payload = bytes(data[HEADER_SIZE:])

        expected_checksum = compute_checksum(opcode, seq_id, payload)
        if received_checksum != expected_checksum:
            raise ChecksumMismatchError(
                f"Checksum mismatch: received 0x{received_checksum:04X}, "
                f"calculated 0x{expected_checksum:04X}"
            )

        return cls(opcode=opcode, sequence_id=seq_id, payload=payload)
