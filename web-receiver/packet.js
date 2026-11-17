/**
 * ChirpDrop - Binary Packet Framing and Validation Module (JavaScript)
 * --------------------------------------------------------------------
 * Mirrors the Python binary packet framing protocol defined in app/core/packet.py
 * and app/communication/packet_codec.py.
 *
 * Header Specification (8 bytes):
 * +------------------+---------------+-------------------+------------------+
 * | Magic Preamble   | Opcode        | Sequence Number   | Checksum         |
 * | b"CD\x01" (3B)   | uint8 (1B)    | uint16 BE (2B)    | uint16 BE (2B)   |
 * +------------------+---------------+-------------------+------------------+
 * Checksum: Lower 16 bits of IEEE 802.3 CRC-32 computed over:
 *   MAGIC (3B) + Opcode (1B) + Sequence (2B) + Payload (NB)
 */

(function (global) {
    'use strict';

    // Protocol Constants
    const MAGIC_0 = 0x43; // 'C'
    const MAGIC_1 = 0x44; // 'D'
    const MAGIC_2 = 0x01; // 0x01

    const HEADER_SIZE = 8;
    const MAX_PAYLOAD_SIZE = 120;
    const MAX_PACKET_SIZE = 128;

    const Opcode = Object.freeze({
        SYN: 0x01,
        DATA: 0x02,
        NACK: 0x03,
        FIN: 0x04,
        properties: {
            1: { name: 'SYN', description: 'Session Synchronization' },
            2: { name: 'DATA', description: 'Data Payload' },
            3: { name: 'NACK', description: 'Retransmission Request' },
            4: { name: 'FIN', description: 'Session Finalization' },
        }
    });

    // IEEE 802.3 CRC-32 Table
    let crcTable = null;
    function getCrcTable() {
        if (!crcTable) {
            crcTable = new Uint32Array(256);
            for (let i = 0; i < 256; i++) {
                let c = i;
                for (let k = 0; k < 8; k++) {
                    c = (c & 1) ? (0xEDB88320 ^ (c >>> 1)) : (c >>> 1);
                }
                crcTable[i] = c;
            }
        }
        return crcTable;
    }

    /**
     * Calculate 32-bit CRC matching Python zlib.crc32.
     * @param {Uint8Array} buffer
     * @returns {number} Unsigned 32-bit integer
     */
    function crc32(buffer) {
        const table = getCrcTable();
        let crc = 0xFFFFFFFF;
        for (let i = 0; i < buffer.length; i++) {
            crc = (crc >>> 8) ^ table[(crc ^ buffer[i]) & 0xFF];
        }
        return (crc ^ 0xFFFFFFFF) >>> 0;
    }

    /**
     * Compute 16-bit packet checksum (lower 16 bits of CRC-32).
     * @param {number} opcode
     * @param {number} sequenceId
     * @param {Uint8Array} payload
     * @returns {number} 16-bit unsigned integer (0-65535)
     */
    function computeChecksum(opcode, sequenceId, payload) {
        const checkBuf = new Uint8Array(6 + payload.length);
        checkBuf[0] = MAGIC_0;
        checkBuf[1] = MAGIC_1;
        checkBuf[2] = MAGIC_2;
        checkBuf[3] = opcode & 0xFF;
        checkBuf[4] = (sequenceId >> 8) & 0xFF;
        checkBuf[5] = sequenceId & 0xFF;
        checkBuf.set(payload, 6);

        return crc32(checkBuf) & 0xFFFF;
    }

    /**
     * Decode a Base64 string into a Uint8Array.
     * Handles padding and whitespace cleanly.
     * @param {string} b64
     * @returns {Uint8Array}
     */
    function base64ToBytes(b64) {
        const clean = b64.trim().replace(/[\r\n\t ]/g, '');
        const binaryStr = atob(clean);
        const bytes = new Uint8Array(binaryStr.length);
        for (let i = 0; i < binaryStr.length; i++) {
            bytes[i] = binaryStr.charCodeAt(i);
        }
        return bytes;
    }

    /**
     * Parse and validate a binary packet buffer or Base64 string.
     * @param {string|Uint8Array} input - Base64 encoded string or raw Uint8Array
     * @returns {Object} Result object with validation details
     */
    function decodePacket(input) {
        let bytes;
        let rawBase64 = null;

        if (typeof input === 'string') {
            rawBase64 = input.trim();
            try {
                bytes = base64ToBytes(rawBase64);
            } catch (err) {
                return {
                    isValid: false,
                    error: `Base64 decoding failed: ${err.message}`,
                    rawText: input
                };
            }
        } else if (input instanceof Uint8Array) {
            bytes = input;
        } else {
            return {
                isValid: false,
                error: `Expected string or Uint8Array, received ${typeof input}`
            };
        }

        // 1. Length Check
        if (bytes.length < HEADER_SIZE) {
            return {
                isValid: false,
                error: `Packet too short: ${bytes.length} bytes (minimum is ${HEADER_SIZE} bytes)`,
                rawBytes: bytes
            };
        }

        if (bytes.length > MAX_PACKET_SIZE) {
            return {
                isValid: false,
                error: `Packet exceeds maximum size: ${bytes.length} > ${MAX_PACKET_SIZE} bytes`,
                rawBytes: bytes
            };
        }

        // 2. Magic Preamble Check (b"CD\x01")
        if (bytes[0] !== MAGIC_0 || bytes[1] !== MAGIC_1 || bytes[2] !== MAGIC_2) {
            return {
                isValid: false,
                error: `Invalid magic preamble: [0x${bytes[0].toString(16)}, 0x${bytes[1].toString(16)}, 0x${bytes[2].toString(16)}]`,
                rawBytes: bytes
            };
        }

        // 3. Opcode Check
        const opcode = bytes[3];
        const opcodeInfo = Opcode.properties[opcode];
        if (!opcodeInfo) {
            return {
                isValid: false,
                error: `Unsupported opcode: 0x${opcode.toString(16)}`,
                rawBytes: bytes
            };
        }

        // 4. Sequence Number (Big-endian uint16)
        const sequenceId = (bytes[4] << 8) | bytes[5];

        // 5. Header Checksum (Big-endian uint16)
        const headerChecksum = (bytes[6] << 8) | bytes[7];

        // 6. Payload Extraction
        const payload = bytes.slice(HEADER_SIZE);
        if (payload.length > MAX_PAYLOAD_SIZE) {
            return {
                isValid: false,
                error: `Payload size (${payload.length} bytes) exceeds limit (${MAX_PAYLOAD_SIZE} bytes)`,
                opcode,
                sequenceId
            };
        }

        // 7. Checksum Verification
        const calculatedChecksum = computeChecksum(opcode, sequenceId, payload);
        const checksumMatches = (calculatedChecksum === headerChecksum);

        if (!checksumMatches) {
            return {
                isValid: false,
                error: `Checksum mismatch: expected 0x${headerChecksum.toString(16).toUpperCase().padStart(4, '0')}, computed 0x${calculatedChecksum.toString(16).toUpperCase().padStart(4, '0')}`,
                opcode,
                opcodeName: opcodeInfo.name,
                sequenceId,
                headerChecksum,
                calculatedChecksum,
                payload
            };
        }

        // 8. Text Decoding for UTF-8 Payload
        let text = null;
        try {
            const decoder = new TextDecoder('utf-8', { fatal: true });
            text = decoder.decode(payload);
        } catch {
            // Non-fatal if payload is binary
            text = `[Binary Payload: ${payload.length} bytes]`;
        }

        return {
            isValid: true,
            rawBase64,
            opcode,
            opcodeName: opcodeInfo.name,
            sequenceId,
            checksum: headerChecksum,
            calculatedChecksum,
            payloadSize: payload.length,
            payload,
            text,
            timestamp: new Date()
        };
    }

    // Export module
    global.ChirpDropPacket = {
        Opcode,
        HEADER_SIZE,
        MAX_PAYLOAD_SIZE,
        MAX_PACKET_SIZE,
        crc32,
        computeChecksum,
        base64ToBytes,
        decodePacket
    };

})(typeof window !== 'undefined' ? window : global);
