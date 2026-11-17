"""
ChirpDrop - Packet Codec Module
-------------------------------
Provides bidirectional lossless encoding between ChirpDrop binary Packet objects
and ASCII Base64 text compatible with the GGWave acoustic modem.
"""

import base64
import binascii
import logging
from typing import Union

from app.core import (
    ChecksumMismatchError,
    InvalidMagicError,
    InvalidPacketLengthError,
    InvalidSequenceNumberError,
    OversizedPayloadError,
    Packet,
    PacketError,
    UnsupportedOpcodeError,
)

logger = logging.getLogger("ChirpDrop.PacketCodec")


# ---------------------------------------------------------------------------
# Custom Codec Exceptions
# ---------------------------------------------------------------------------
class PacketCodecError(Exception):
    """Base exception for packet codec encoding and decoding errors."""


class PacketEncodingError(PacketCodecError):
    """Raised when serialization or text encoding of a Packet fails."""


class PacketDecodingError(PacketCodecError):
    """Raised when text representation cannot be converted to a binary Packet."""


class CorruptedPacketDataError(PacketDecodingError):
    """Raised when decoded packet data fails CRC-16 checksum or structural validation."""


# ---------------------------------------------------------------------------
# Codec Functions
# ---------------------------------------------------------------------------
def encode_packet_to_text(packet: Packet) -> str:
    """
    Serialize a ChirpDrop Packet into a lossless Base64 ASCII text representation.

    Args:
        packet: Validated Packet object to serialize.

    Returns:
        ASCII string containing the Base64 representation of the binary packet.

    Raises:
        PacketEncodingError: If the input is not a Packet or serialization fails.
    """
    if not isinstance(packet, Packet):
        raise PacketEncodingError(
            f"Expected a Packet instance, got {type(packet).__name__}"
        )

    try:
        binary_data = packet.to_bytes()
        b64_ascii = base64.b64encode(binary_data).decode("ascii")
        return b64_ascii
    except Exception as err:
        logger.error(f"Failed to encode packet to Base64 text: {err}")
        raise PacketEncodingError(f"Packet text encoding failed: {err}") from err


def decode_text_to_packet(text_or_bytes: Union[str, bytes]) -> Packet:
    """
    Decode Base64 text or bytes received from GGWave into a validated Packet object.

    Enforces strict Base64 validation, header checks, opcode checks, and CRC-16
    checksum verification.

    Args:
        text_or_bytes: ASCII/UTF-8 string or bytes containing Base64 packet data.

    Returns:
        Reconstructed and cryptographically verified Packet object.

    Raises:
        PacketDecodingError: If input cannot be parsed as Base64 or is malformed.
        CorruptedPacketDataError: If checksum verification fails or payload is corrupted.
    """
    if not isinstance(text_or_bytes, (str, bytes, bytearray)):
        raise PacketDecodingError(
            f"Input must be str or bytes, got {type(text_or_bytes).__name__}"
        )

    # 1. Normalize input to ASCII string
    if isinstance(text_or_bytes, (bytes, bytearray)):
        try:
            ascii_text = text_or_bytes.decode("ascii").strip()
        except UnicodeDecodeError as err:
            logger.warning(f"Incoming payload is not valid ASCII text: {err}")
            raise PacketDecodingError(f"Non-ASCII data received: {err}") from err
    else:
        ascii_text = text_or_bytes.strip()

    if not ascii_text:
        raise PacketDecodingError("Cannot decode an empty text payload.")

    # 2. Strict Base64 decoding
    try:
        raw_binary = base64.b64decode(ascii_text, validate=True)
    except binascii.Error as err:
        logger.warning(f"Base64 validation failed: {err}")
        raise PacketDecodingError(f"Invalid Base64 payload: {err}") from err

    # 3. Reconstruct and validate binary Packet
    try:
        packet = Packet.from_bytes(raw_binary)
        return packet
    except ChecksumMismatchError as err:
        logger.warning(f"Packet rejected due to checksum mismatch: {err}")
        raise CorruptedPacketDataError(f"Packet integrity check failed: {err}") from err
    except (
        InvalidMagicError,
        UnsupportedOpcodeError,
        InvalidPacketLengthError,
        OversizedPayloadError,
        InvalidSequenceNumberError,
    ) as err:
        logger.warning(f"Packet rejected due to protocol framing error: {err}")
        raise PacketDecodingError(f"Malformed packet framing: {err}") from err
    except Exception as err:
        logger.error(f"Unexpected error during packet deserialization: {err}")
        raise PacketDecodingError(f"Failed to reconstruct packet: {err}") from err
