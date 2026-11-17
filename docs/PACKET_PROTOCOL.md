# ChirpDrop Binary Packet Protocol Specification

This document details the binary packet framing and serialization specification for ChirpDrop's air-gapped acoustic transport subsystem.

---

## 1. Frame Architecture & Binary Layout

Every transmission frame in ChirpDrop is packed into a compact binary representation structured as an **8-byte header** followed by a variable-length **payload** (0 to 120 bytes).

### Binary Frame Diagram

```text
 0                   1                   2                   3
 0 1 2 3 4 5 6 7 8 9 0 1 2 3 4 5 6 7 8 9 0 1 2 3 4 5 6 7 8 9 0 1
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
|       Magic Preamble ('C', 'D', 0x01)         |    Opcode     |
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
|        Sequence ID            |       CRC-16 Checksum         |
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
|                                                               |
|                  Payload (0 to 120 Bytes)                     |
|                                                               |
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
```

### Protocol Constants

| Constant | Value | Description |
| :--- | :--- | :--- |
| `MAGIC` | `b"CD\x01"` (3 bytes) | Fixed synchronization marker. |
| `HEADER_SIZE` | `8` bytes | Fixed size of the binary header. |
| `MAX_PAYLOAD_SIZE`| `120` bytes | Maximum allowable payload bytes per packet. |
| `MAX_PACKET_SIZE` | `128` bytes | Maximum total packet size (`HEADER_SIZE + MAX_PAYLOAD_SIZE`). |
| `HEADER_FORMAT` | `">3sBHH"` | Big-endian struct format for binary header packing. |

---

## 2. Header Field Definitions

| Byte Offset | Field Name | Width | Type / Endianness | Protocol Description |
| :--- | :--- | :--- | :--- | :--- |
| **0 – 2** | `Magic` | 3 Bytes | Fixed ASCII + binary | Must equal `b"CD\x01"` (`0x43`, `0x44`, `0x01`). Packets lacking this marker are discarded immediately. |
| **3** | `Opcode` | 1 Byte | `uint8` (Unsigned Char) | Operation code indicating frame type and receiver action. |
| **4 – 5** | `Sequence ID` | 2 Bytes | `uint16` (Big-Endian) | Monotonically increasing sequence number from `0` to `65535`. |
| **6 – 7** | `Checksum` | 2 Bytes | `uint16` (Big-Endian) | Lower 16 bits of CRC-32 computed over header and payload (excluding checksum itself). |
| **8 – N** | `Payload` | 0–120 Bytes | Raw bytes | Application payload data (message text or compressed file chunk). |

---

## 3. Protocol Opcodes

| Opcode Name | Hex Value | Decimal | Operational Purpose |
| :--- | :--- | :--- | :--- |
| `SYN` | `0x01` | 1 | **Session Synchronization**: Handshake initiation, session parameters, and sequence reset. |
| `DATA` | `0x02` | 2 | **Data Packet**: Carries an application payload chunk (0 to 120 bytes). |
| `NACK` | `0x03` | 3 | **Negative Acknowledgment**: Sent by the receiver to request selective retransmission of missing sequence numbers. |
| `FIN` | `0x04` | 4 | **Session Finalization**: Transmission completion, session termination, and end-of-transfer handshake. |

---

## 4. Checksum Implementation (CRC-16)

To minimize packet overhead while maintaining resilience against acoustic bitflips and environmental noise:

1. **Algorithm**: Standard `zlib.crc32()`, masked to the lower 16 bits (`crc32(buffer) & 0xFFFF`).
2. **Buffer Coverage**:
   $$\text{Checksum Buffer} = \text{MAGIC} + \text{OPCODE} + \text{SEQUENCE\_ID} + \text{PAYLOAD}$$
   Specifically:
   - Magic (3 bytes: `b"CD\x01"`)
   - Opcode (1 byte: `uint8`)
   - Sequence ID (2 bytes: big-endian `uint16`)
   - Payload ($N$ bytes: raw binary data)
3. **Exclusion**: The 2 checksum bytes themselves are excluded from the calculation.
4. **Endianness**: The resulting 16-bit integer is stored in big-endian byte order (`>H`).

---

## 5. Serialization & Deserialization Pipeline

### Serialization (`Packet.to_bytes()`)
1. **Validation**: Calls `self.validate()` to ensure:
   - `opcode` is a valid member of `Opcode`.
   - `sequence_id` is an integer satisfying $0 \le \text{sequence\_id} \le 65535$.
   - `payload` is `bytes` or `bytearray` and $\text{len}(\text{payload}) \le 120$.
2. **Checksum Calculation**: Computes the 16-bit CRC using `compute_checksum()`.
3. **Header Packing**: Packs `MAGIC`, `opcode`, `sequence_id`, and `checksum` using `struct.pack(">3sBHH", ...)`.
4. **Assembly**: Concatenates `header + payload` and returns the resulting byte sequence.

### Deserialization (`Packet.from_bytes()`)
1. **Length Check**: Verifies that input length $\ge 8$ bytes (`InvalidPacketLengthError`) and payload $\le 120$ bytes (`OversizedPayloadError`).
2. **Magic Validation**: Verifies that bytes 0–2 match `b"CD\x01"` (`InvalidMagicError`).
3. **Header Unpacking**: Unpacks opcode, sequence number, and received checksum via `struct.unpack(">3sBHH", data[:8])`.
4. **Opcode Validation**: Verifies that the opcode corresponds to a valid `Opcode` enum member (`UnsupportedOpcodeError`).
5. **Checksum Verification**: Recomputes the checksum over `MAGIC + opcode + sequence_id + payload`. If it does not equal the received checksum, raises `ChecksumMismatchError`.
6. **Instantiation**: Returns a clean `Packet(opcode, sequence_id, payload)` instance.

---

## 6. Hexadecimal Packet Example

### Scenario: DATA Packet Transmission

- **Opcode**: `DATA` (`0x02`)
- **Sequence ID**: `42` (`0x002A`)
- **Payload**: `b"Hello, ChirpDrop Acoustic World!"` (32 bytes)

### Raw Hexadecimal Dump (40 Bytes Total)

```text
43 44 01 02 00 2a 5c bc 48 65 6c 6c 6f 2c 20 43 68 69 72 70 44 72 6f 70 20 41 63 6f 75 73 74 69 63 20 57 6f 72 6c 64 21
```

### Detailed Byte Breakdown

| Offset | Hex Bytes | ASCII / Value | Component | Description |
| :--- | :--- | :--- | :--- | :--- |
| `0x00 - 0x02` | `43 44 01` | `'C' 'D' '\x01'` | Magic Preamble | Unique identifier for ChirpDrop packets |
| `0x03` | `02` | `2` | Opcode | `Opcode.DATA` |
| `0x04 - 0x05` | `00 2a` | `42` | Sequence ID | Unsigned 16-bit sequence number (big-endian) |
| `0x06 - 0x07` | `5c bc` | `0x5CBC` | CRC-16 Checksum | Lower 16 bits of CRC-32 over header + payload |
| `0x08 - 0x27` | `48 65 6c ... 64 21` | `"Hello, ... World!"` | Payload | 32-byte application payload |

---

## 7. Exception Hierarchy

All framing-related exceptions inherit from `PacketError`:

```text
Exception
└── PacketError
    ├── InvalidMagicError
    ├── UnsupportedOpcodeError
    ├── InvalidPacketLengthError
    │   └── OversizedPayloadError
    ├── InvalidSequenceNumberError
    └── ChecksumMismatchError
```
