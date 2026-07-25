"""Prove material.bake_detail transfers high-poly detail onto a low-poly mesh.

The check that matters is not "did a PNG appear" -- a broken bake also writes a
PNG, just a flat lilac one. So this measures the normal map's actual deviation
from flat (128,128,255) and fails if the surface came out featureless.
"""

import os
import struct
import sys
import zlib

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from bforge import Forge  # noqa: E402


def _decode(path):
    """Minimal PNG reader (8-bit, non-interlaced) -- avoids a Pillow dependency."""
    data = open(path, "rb").read()
    assert data[:8] == b"\x89PNG\r\n\x1a\n", "not a PNG"
    pos = 8
    idat = b""
    width = height = depth = color = None
    while pos < len(data):
        ln = struct.unpack(">I", data[pos : pos + 4])[0]
        typ = data[pos + 4 : pos + 8]
        body = data[pos + 8 : pos + 8 + ln]
        if typ == b"IHDR":
            width, height, depth, color = struct.unpack(">IIBB", body[:10])
        elif typ == b"IDAT":
            idat += body
        elif typ == b"IEND":
            break
        pos += 12 + ln
    assert depth == 8, f"expected 8-bit PNG, got {depth}"
    channels = {0: 1, 2: 3, 4: 2, 6: 4}[color]
    raw = zlib.decompress(idat)
    stride = width * channels
    out = bytearray()
    prev = bytearray(stride)
    p = 0
    for _ in range(height):
        f = raw[p]
        p += 1
        line = bytearray(raw[p : p + stride])
        p += stride
        if f == 1:
            for i in range(channels, stride):
                line[i] = (line[i] + line[i - channels]) & 0xFF
        elif f == 2:
            for i in range(stride):
                line[i] = (line[i] + prev[i]) & 0xFF
        elif f == 3:
            for i in range(stride):
                a = line[i - channels] if i >= channels else 0
                line[i] = (line[i] + ((a + prev[i]) >> 1)) & 0xFF
        elif f == 4:
            for i in range(stride):
                a = line[i - channels] if i >= channels else 0
                c = prev[i - channels] if i >= channels else 0
                b = prev[i]
                pa, pb, pc = abs(b - c), abs(a - c), abs(a + b - 2 * c)
                pr = a if (pa <= pb and pa <= pc) else (b if pb <= pc else c)
                line[i] = (line[i] + pr) & 0xFF
        out += line
        prev = line
    return width, height, channels, bytes(out)


def normal_map_stats(path):
    """Return (deviation_fraction, mean_abs_xy) for a tangent-space normal map.

    A flat map is (128,128,255) everywhere. Real transferred detail perturbs R/G.
    """
    w, h, ch, px = _decode(path)
    perturbed = 0
    total = 0
    acc = 0
    for i in range(0, len(px), ch):
        r, g, b = px[i], px[i + 1], px[i + 2]
        if r == 0 and g == 0 and b == 0:
            continue  # unbaked background
        total += 1
        d = abs(r - 128) + abs(g - 128)
        acc += d
        if d > 12:
            perturbed += 1
    if total == 0:
        return 0.0, 0.0
    return perturbed / total, acc / total


def main():
    with Forge() as forge:
        forge.call("session.reset")

        # Low-poly target: a plain sphere.
        forge.call("build.sphere", name="rock_low", material="stone")
        forge.call("uv.unwrap", object="rock_low", style="smart_packed")

        # High-poly source: same shape, subdivided and noise-displaced so it has
        # detail the low-poly genuinely does not.
        forge.call("build.sphere", name="rock_high", material="stone")
        forge.call("build.subdivide", name="rock_high", cuts=3, smooth=0.0)
        forge.call("build.deform", name="rock_high", mode="noise", amount=0.06, frequency=9.0)

        low = forge.call("object.inspect", name="rock_low")
        high = forge.call("object.inspect", name="rock_high")
        print(f"low  : {low.get('triangles')} tris")
        print(f"high : {high.get('triangles')} tris")

        result = forge.call(
            "material.bake_detail",
            low="rock_low",
            high=["rock_high"],
            pass_name="normal",
            size=512,
            samples=8,
            cage_extrusion=0.03,
            max_ray_distance=0.12,
        )
        print("baked ->", result["rel"])

        path = result["texture"]
        frac, mean = normal_map_stats(path)
        print(f"perturbed texels: {frac:.1%}   mean |dR|+|dG|: {mean:.1f}")

        if frac < 0.10:
            print("FAIL: normal map is essentially flat — no detail was transferred")
            return 1
        print("PASS: high-poly detail landed on the low-poly mesh")

        # The high-poly is scaffolding; it must not ship.
        forge.call("object.delete", names=["rock_high"])
        sheet = forge.call("render.contact_sheet", out="rock_detail.png", tile=320, samples=24)
        print("contact sheet ->", sheet.get("rel") or sheet.get("path"))
        return 0


if __name__ == "__main__":
    sys.exit(main())
