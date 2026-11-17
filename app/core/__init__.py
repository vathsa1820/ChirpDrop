"""
ChirpDrop - Core Protocol Package
---------------------------------
Exports protocol framing, packet data structures, opcodes, and custom exceptions.
"""

from app.core.packet import (
    HEADER_FORMAT,
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
    PacketError,
    UnsupportedOpcodeError,
    compute_checksum,
)

__all__ = [
    "MAGIC",
    "HEADER_SIZE",
    "MAX_PAYLOAD_SIZE",
    "MAX_PACKET_SIZE",
    "HEADER_FORMAT",
    "Opcode",
    "Packet",
    "compute_checksum",
    "PacketError",
    "InvalidMagicError",
    "UnsupportedOpcodeError",
    "InvalidPacketLengthError",
    "OversizedPayloadError",
    "InvalidSequenceNumberError",
    "ChecksumMismatchError",
]
