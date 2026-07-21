#!/usr/bin/env python3
"""Compare two PNGs pixel-by-pixel with a tolerance (visual regression gate).

  python tools/screenshots/compare_screenshots.py baseline.png candidate.png \
      [--max-diff-ratio 0.001] [--channel-tolerance 8]

Exit 0 when the fraction of pixels whose per-channel delta exceeds
--channel-tolerance is at most --max-diff-ratio; exit 1 otherwise.
Stdlib + zlib PNG decode (no Pillow dependency) — 8-bit RGB/RGBA non-interlaced.
"""

from __future__ import annotations

import argparse
import struct
import sys
import zlib


def decode_png(path: str) -> tuple[int, int, bytes, int]:
    with open(path, "rb") as fh:
        data = fh.read()
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        raise SystemExit(f"{path}: not a PNG")
    pos = 8
    width = height = 0
    bit_depth = color_type = interlace = None
    idat = bytearray()
    while pos < len(data):
        (length,) = struct.unpack(">I", data[pos : pos + 4])
        ctype = data[pos + 4 : pos + 8]
        chunk = data[pos + 8 : pos + 8 + length]
        if ctype == b"IHDR":
            width, height, bit_depth, color_type, _comp, _filt, interlace = struct.unpack(
                ">IIBBBBB", chunk
            )
        elif ctype == b"IDAT":
            idat += chunk
        elif ctype == b"IEND":
            break
        pos += 12 + length
    if bit_depth != 8 or interlace != 0 or color_type not in (2, 6):
        raise SystemExit(f"{path}: unsupported PNG (need 8-bit RGB/RGBA non-interlaced)")
    channels = 3 if color_type == 2 else 4
    raw = zlib.decompress(bytes(idat))
    stride = width * channels
    pixels = bytearray(height * stride)
    prev = bytearray(stride)
    src = 0
    for y in range(height):
        filter_type = raw[src]
        src += 1
        line = bytearray(raw[src : src + stride])
        src += stride
        if filter_type == 1:  # Sub
            for i in range(channels, stride):
                line[i] = (line[i] + line[i - channels]) & 0xFF
        elif filter_type == 2:  # Up
            for i in range(stride):
                line[i] = (line[i] + prev[i]) & 0xFF
        elif filter_type == 3:  # Average
            for i in range(stride):
                a = line[i - channels] if i >= channels else 0
                line[i] = (line[i] + ((a + prev[i]) >> 1)) & 0xFF
        elif filter_type == 4:  # Paeth
            for i in range(stride):
                a = line[i - channels] if i >= channels else 0
                b = prev[i]
                c = prev[i - channels] if i >= channels else 0
                p = a + b - c
                pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                pred = a if (pa <= pb and pa <= pc) else (b if pb <= pc else c)
                line[i] = (line[i] + pred) & 0xFF
        pixels[y * stride : (y + 1) * stride] = line
        prev = line
    return width, height, bytes(pixels), channels


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("baseline")
    parser.add_argument("candidate")
    parser.add_argument("--max-diff-ratio", type=float, default=0.001)
    parser.add_argument("--channel-tolerance", type=int, default=8)
    args = parser.parse_args()

    w1, h1, px1, ch1 = decode_png(args.baseline)
    w2, h2, px2, ch2 = decode_png(args.candidate)
    if (w1, h1) != (w2, h2):
        print(f"FAIL: size mismatch {w1}x{h1} vs {w2}x{h2}")
        return 1
    if ch1 != ch2:
        print(f"FAIL: channel mismatch {ch1} vs {ch2}")
        return 1

    total = w1 * h1
    diff = 0
    step = ch1
    for i in range(0, len(px1), step):
        for c in range(3):  # ignore alpha
            if abs(px1[i + c] - px2[i + c]) > args.channel_tolerance:
                diff += 1
                break
    ratio = diff / total
    status = "OK" if ratio <= args.max_diff_ratio else "FAIL"
    print(
        f"{status}: {diff}/{total} pixels differ beyond ±{args.channel_tolerance} "
        f"(ratio {ratio:.6f}, threshold {args.max_diff_ratio})"
    )
    return 0 if status == "OK" else 1


if __name__ == "__main__":
    sys.exit(main())
