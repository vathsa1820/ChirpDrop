"""
ChirpDrop - PNG Icon Generator
------------------------------
Generates valid 192x192 and 512x512 PNG app icons for PWA & iOS Safari
using only Python standard library (struct + zlib). No external dependencies.
"""

import math
from pathlib import Path
import struct
import zlib

def generate_icon(width: int, height: int, output_path: Path) -> None:
    raw = bytearray()
    cx, cy = width / 2.0, height / 2.0
    corner_radius = width * 0.22

    for y in range(height):
        raw.append(0)  # Filter type: None
        for x in range(width):
            # Check rounded corner mask
            dx = max(0.0, abs(x - cx) - (cx - corner_radius))
            dy = max(0.0, abs(y - cy) - (cy - corner_radius))
            outside_corner = (dx * dx + dy * dy) > (corner_radius * corner_radius)

            if outside_corner:
                raw.extend([0, 0, 0, 0])
                continue

            # Deep dark background gradient
            grad = y / float(height)
            r = int(15 + 10 * (1.0 - grad))
            g = int(23 + 12 * (1.0 - grad))
            b = int(42 + 20 * (1.0 - grad))
            a = 255

            # Circular concentric sound rings
            dist = math.hypot(x - cx, y - cy)
            r1 = width * 0.35
            r2 = width * 0.22

            if abs(dist - r1) < width * 0.012:
                # Cyan ring
                r, g, b = 6, 182, 212
            elif abs(dist - r2) < width * 0.016:
                # Emerald ring
                r, g, b = 16, 185, 129

            # Center audio wave bars
            bar_spacing = width * 0.08
            bars = [
                (-2 * bar_spacing, width * 0.04),
                (-1 * bar_spacing, width * 0.14),
                (0.0,              width * 0.28),
                (1 * bar_spacing,  width * 0.18),
                (2 * bar_spacing,  width * 0.08),
            ]
            bar_width = width * 0.035

            for bx, bh in bars:
                if abs(x - (cx + bx)) <= bar_width and abs(y - cy) <= bh:
                    # Vibrant gradient for bars
                    bar_frac = (bh - abs(y - cy)) / bh
                    r = int(6 + (56 - 6) * bar_frac)
                    g = int(182 + (230 - 182) * bar_frac)
                    b = int(212 + (255 - 212) * bar_frac)

            raw.extend([r, g, b, a])

    def make_chunk(tag: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + tag
            + data
            + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
        )

    ihdr = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    idat = zlib.compress(bytes(raw), 9)
    png_data = (
        b"\x89PNG\r\n\x1a\n"
        + make_chunk(b"IHDR", ihdr)
        + make_chunk(b"IDAT", idat)
        + make_chunk(b"IEND", b"")
    )

    output_path.write_bytes(png_data)
    print(f"Generated {output_path.name} ({width}x{height}, {len(png_data)} bytes)")

if __name__ == "__main__":
    out_dir = Path(__file__).resolve().parent
    generate_icon(192, 192, out_dir / "icon-192.png")
    generate_icon(512, 512, out_dir / "icon-512.png")
