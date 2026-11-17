"""
ChirpDrop - Communication Subsystem Package
-------------------------------------------
Exports the packet codec and acoustic transport layer for air-gapped packet communication.
"""

from app.communication.packet_codec import (
    CorruptedPacketDataError,
    PacketCodecError,
    PacketDecodingError,
    PacketEncodingError,
    decode_text_to_packet,
    encode_packet_to_text,
)
from app.communication.acoustic_transport import (
    AcousticTransport,
    AcousticTransportError,
    TransmissionError,
)

__all__ = [
    # Packet Codec
    "encode_packet_to_text",
    "decode_text_to_packet",
    "PacketCodecError",
    "PacketEncodingError",
    "PacketDecodingError",
    "CorruptedPacketDataError",
    # Acoustic Transport
    "AcousticTransport",
    "AcousticTransportError",
    "TransmissionError",
]
