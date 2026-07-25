"""Is the baked texture ACTUALLY seamless?

A tiling texture that seams is worse than no texture: the repeat becomes a grid
of visible lines across a whole building. "A PNG appeared" proves nothing, so
this decodes the map and compares the wrapped edges — column 0 against column
w-1, row 0 against row h-1 — against the noise floor of neighbouring columns
inside the image.

If the wrap discontinuity is no worse than an ordinary interior step, it tiles.

    python tools/bforge/tests/test_tileable.py
"""

from __future__ import annotations

import struct
import sys
import zlib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bforge import Forge  # noqa: E402


def read_png(path: Path):
    """Minimal PNG decoder — stdlib only, no Pillow in the tools venv."""
    data = path.read_bytes()
    assert data[:8] == b"\x89PNG\r\n\x1a\n", "not a PNG"
    pos, idat, width, height, depth, colour = 8, b"", 0, 0, 0, 0
    while pos < len(data):
        (length,) = struct.unpack(">I", data[pos : pos + 4])
        kind = data[pos + 4 : pos + 8]
        body = data[pos + 8 : pos + 8 + length]
        if kind == b"IHDR":
            width, height, depth, colour = struct.unpack(">IIBB", body[:10])
        elif kind == b"IDAT":
            idat += body
        elif kind == b"IEND":
            break
        pos += 12 + length
    assert depth == 8, f"expected 8-bit, got {depth}"
    channels = {0: 1, 2: 3, 4: 2, 6: 4}[colour]
    raw = zlib.decompress(idat)
    stride = width * channels
    out, previous = [], bytearray(stride)
    pos = 0
    for _row in range(height):
        filt = raw[pos]
        line = bytearray(raw[pos + 1 : pos + 1 + stride])
        pos += 1 + stride
        for i in range(stride):
            a = line[i - channels] if i >= channels else 0
            b = previous[i]
            c = previous[i - channels] if i >= channels else 0
            if filt == 1:
                line[i] = (line[i] + a) & 0xFF
            elif filt == 2:
                line[i] = (line[i] + b) & 0xFF
            elif filt == 3:
                line[i] = (line[i] + (a + b) // 2) & 0xFF
            elif filt == 4:
                p = a + b - c
                pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                pred = a if (pa <= pb and pa <= pc) else (b if pb <= pc else c)
                line[i] = (line[i] + pred) & 0xFF
        out.append(bytes(line))
        previous = line
    return width, height, channels, out


def mean_abs_delta(rows, channels, pairs):
    total = count = 0
    for (ax, ay), (bx, by) in pairs:
        for c in range(min(3, channels)):
            total += abs(rows[ay][ax * channels + c] - rows[by][bx * channels + c])
            count += 1
    return total / max(1, count)


def check(path: Path) -> tuple[float, float]:
    width, height, channels, rows = read_png(path)
    # Wrap seam: last column vs first column, last row vs first row.
    wrap = [((width - 1, y), (0, y)) for y in range(height)]
    wrap += [((x, height - 1), (x, 0)) for x in range(width)]
    # Control: an ordinary interior step, the natural noise floor of this map.
    interior = [((x, y), (x + 1, y)) for y in range(0, height, 4) for x in range(0, width - 1, 7)]
    return mean_abs_delta(rows, channels, wrap), mean_abs_delta(rows, channels, interior)


def main() -> int:
    failures = []
    with Forge(workdir=".", out_dir="assets-generated/bforge") as forge:
        forge.call("session.reset")
        forge.call("build.box", name="wall", size=[8.0, 0.5, 5.0], material="", uv="none")
        result = forge.call(
            "material.tileable",
            object="wall",
            base_color="#c2ab84",
            roughness=0.82,
            detail_scale=5.0,
            dirt=0.4,
            bump=0.45,
            tiles=4.0,
            uv_scale=2.0,
            size=256,
            samples=8,
            stem="seamcheck",
            _timeout=2400,
        )
        print(f"baked: {list(result['maps'])}")
        if not result["gltf_safe"]:
            failures.append("material is not glTF-safe after tiling")

        for name, rel in result["maps"].items():
            path = Path(rel)
            if not path.is_file():
                failures.append(f"{name}: missing at {rel}")
                continue
            seam, floor = check(path)
            ratio = seam / max(floor, 0.01)
            verdict = "ok  " if ratio <= 2.0 else "SEAM"
            print(
                f"{verdict} {name:11} wrap delta {seam:6.2f}   interior {floor:6.2f}   "
                f"ratio {ratio:.2f}x"
            )
            if ratio > 2.0:
                failures.append(
                    f"{name}: wrap seam is {ratio:.1f}x the interior noise floor — "
                    "the texture does not tile"
                )

    if failures:
        print("\nFAILURES:")
        for failure in failures:
            print(f"  - {failure}")
        return 1
    print("\ntileable bake: PASS (wrap edges indistinguishable from interior)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
