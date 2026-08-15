"""Post-processing for 2D output — the half of icon quality that is not modelling.

A game icon is not a screenshot. Put the same mesh under a review rig and under
an icon rig and the second one looks like it cost money: the difference is a
separation light on the silhouette, a backdrop that is darker at the edges than
behind the subject, highlight bloom, and a grade. None of that is geometry.

Everything here works on **linear scene-referred float RGBA**, top-down, shaped
``(height, width, 4)``. That matters: bloom, compositing and exposure are only
correct in linear light. Renders reach this module through OpenEXR rather than
PNG for the same reason — an 8-bit PNG has already clipped the highlights that
bloom is supposed to find, so blooming a PNG blooms whatever survived the clip.

Pure numpy plus ``bpy`` for image IO. No operators, so it runs headless.
"""

from __future__ import annotations

import bpy

LUMA = (0.2126, 0.7152, 0.0722)


def require_numpy():
    try:
        import numpy
    except ImportError as exc:  # pragma: no cover - Blender bundles numpy
        raise RuntimeError("numpy is unavailable in this Blender build") from exc
    return numpy


# --------------------------------------------------------------------------
# image IO
# --------------------------------------------------------------------------


def load(path, flip=True):
    """Read an image into a linear float RGBA array, top-down."""
    numpy = require_numpy()
    image = bpy.data.images.load(str(path))
    try:
        width, height = image.size
        data = numpy.array(image.pixels[:], dtype=numpy.float32).reshape((height, width, 4))
        return numpy.flipud(data) if flip else data
    finally:
        bpy.data.images.remove(image)


def premultiply(rgba):
    """Return an RGBA copy whose RGB channels are multiplied by alpha."""
    out = rgba.copy()
    out[..., :3] *= out[..., 3:4]
    return out


def unpremultiply(rgba, epsilon=1e-6):
    """Return straight-alpha RGBA without NaNs or colour in empty pixels."""
    numpy = require_numpy()
    out = rgba.copy()
    alpha = out[..., 3:4]
    out[..., :3] = numpy.divide(
        out[..., :3],
        alpha,
        out=numpy.zeros_like(out[..., :3]),
        where=alpha > epsilon,
    )
    return out


def bleed_transparent_rgb(rgba, radius=8, epsilon=1.0 / 255.0):
    """Dilate straight RGB through transparent pixels without changing alpha.

    Straight-alpha PNGs whose hidden RGB is black acquire a dark seam when a
    GPU filters or builds ordinary mipmaps across the silhouette. Eight local
    dilation steps preserve nearby edge colour; the remaining empty field gets
    the visible mean so even the smallest mip never averages against black.
    """
    numpy = require_numpy()
    out = rgba.copy()
    alpha = out[..., 3]
    known = alpha > epsilon
    if not known.any():
        return out

    rgb = out[..., :3]
    for _ in range(max(0, int(radius))):
        accumulated = numpy.zeros_like(rgb)
        counts = numpy.zeros(alpha.shape, dtype=numpy.float32)

        accumulated[1:] += rgb[:-1] * known[:-1, :, None]
        counts[1:] += known[:-1]
        accumulated[:-1] += rgb[1:] * known[1:, :, None]
        counts[:-1] += known[1:]
        accumulated[:, 1:] += rgb[:, :-1] * known[:, :-1, None]
        counts[:, 1:] += known[:, :-1]
        accumulated[:, :-1] += rgb[:, 1:] * known[:, 1:, None]
        counts[:, :-1] += known[:, 1:]

        fill = (~known) & (counts > 0.0)
        if not fill.any():
            break
        rgb[fill] = accumulated[fill] / counts[fill, None]
        known |= fill

    # Distant transparent pixels only matter in coarse mip levels. A visible
    # mean is deterministic, non-black, and avoids inventing a directional
    # colour gradient where no nearest edge exists.
    fallback = rgb[alpha > epsilon].mean(axis=0, dtype=numpy.float32)
    rgb[~known] = fallback
    return out


def save(array, path, name="_bforge_post", premultiplied=False):
    """Write a display-referred linear RGBA array (top-down) as a PNG.

    Blender applies the sRGB transfer on save. PNG stores straight alpha while
    Cycles EXR returns premultiplied alpha, so callers carrying render data must
    opt into conversion. Transparent RGB is then dilated from the silhouette so
    filtered/mipmapped straight-alpha textures do not acquire dark fringes.
    """
    numpy = require_numpy()
    pixels = unpremultiply(array) if premultiplied else array
    if premultiplied:
        pixels = bleed_transparent_rgb(pixels)
    height, width = pixels.shape[:2]
    image = bpy.data.images.new(name, width=width, height=height, alpha=True)
    try:
        image.alpha_mode = "STRAIGHT"
        # Blender images are bottom-up; ours are top-down.
        image.pixels = numpy.flipud(numpy.clip(pixels, 0.0, 1.0)).ravel().tolist()
        image.filepath_raw = str(path)
        image.file_format = "PNG"
        image.save()
    finally:
        bpy.data.images.remove(image)
    return path


# --------------------------------------------------------------------------
# filters
# --------------------------------------------------------------------------


def box_blur(array, radius, iterations=3):
    """Separable box blur by cumulative sum; 3 passes approximate a gaussian.

    O(pixels) regardless of radius, and exactly reproducible — a real gaussian
    kernel built from floats is neither.
    """
    numpy = require_numpy()
    radius = int(radius)
    if radius < 1:
        return array
    out = array
    for _ in range(max(1, iterations)):
        for axis in (0, 1):
            out = _box_blur_axis(numpy, out, radius, axis)
    return out


def _box_blur_axis(numpy, array, radius, axis):
    moved = numpy.swapaxes(array, 0, axis)
    # Clamp-to-edge padding: zero padding would darken the border, which on a
    # bloom pass reads as a black vignette nobody asked for.
    padded = numpy.concatenate(
        [numpy.repeat(moved[:1], radius, axis=0), moved, numpy.repeat(moved[-1:], radius, axis=0)],
        axis=0,
    )
    sums = numpy.cumsum(padded, axis=0, dtype=numpy.float32)
    sums = numpy.concatenate([numpy.zeros_like(sums[:1]), sums], axis=0)
    window = 2 * radius + 1
    return numpy.swapaxes((sums[window:] - sums[:-window]) / window, 0, axis)


def downsample(array, width, height):
    """Area-average an integer-multiple image down to the requested dimensions.

    Sprite renders are premultiplied linear RGBA. Averaging them in that form
    preserves both sub-pixel silhouette coverage and edge colour; resizing a
    straight-alpha or display-referred image is what creates dark fringes.
    """
    numpy = require_numpy()
    source_height, source_width = array.shape[:2]
    if (source_width, source_height) == (width, height):
        return array
    if width < 1 or height < 1 or source_width % width or source_height % height:
        raise ValueError(
            f"downsample requires an integer reduction, got "
            f"{source_width}x{source_height} -> {width}x{height}"
        )
    scale_x = source_width // width
    scale_y = source_height // height
    if scale_x < 1 or scale_y < 1:
        raise ValueError(
            f"downsample cannot enlarge {source_width}x{source_height} to {width}x{height}"
        )
    shape = (height, scale_y, width, scale_x) + array.shape[2:]
    return array.reshape(shape).mean(axis=(1, 3), dtype=numpy.float32)


def luminance(rgb):
    numpy = require_numpy()
    return rgb @ numpy.array(LUMA, dtype=numpy.float32)


def bloom(rgba, threshold=1.0, strength=0.35, radius=0.04, premultiplied=True):
    """Add a glow around anything brighter than `threshold`.

    Two blur radii, not one: a tight halo reads as a hot specular and a wide one
    reads as atmosphere. Only one of them is the effect people mean by "bloom",
    but a single radius always looks either grimy or radioactive.

    `radius` is a fraction of the image's short side, so a 256 px and a 2048 px
    render of the same asset bloom identically.
    """
    numpy = require_numpy()
    if strength <= 0.0:
        return rgba
    rgb = rgba[..., :3]
    luma = luminance(rgb)
    # Soft knee: a hard threshold makes the bloom boundary visible as a ring.
    knee = numpy.clip((luma - threshold) / max(1e-6, threshold * 0.5 + 1e-6), 0.0, 1.0)
    highlights = rgb * knee[..., None]
    short_side = min(rgba.shape[0], rgba.shape[1])
    tight = box_blur(highlights, max(1, int(short_side * radius * 0.35)))
    wide = box_blur(highlights, max(2, int(short_side * radius * 1.6)))
    glow = (tight * 0.65 + wide * 0.35) * strength
    out = rgba.copy()
    out[..., :3] = rgb + glow
    if premultiplied:
        # Glow spreads past the silhouette. With premultiplied alpha the coverage
        # has to spread with it or the halo is invisible over any background but
        # the one it was composited onto — which is the whole point of shipping
        # an icon with alpha.
        spread = box_blur(rgba[..., 3:4] * knee[..., None], max(2, int(short_side * radius * 1.6)))
        out[..., 3] = numpy.clip(rgba[..., 3] + spread[..., 0] * strength, 0.0, 1.0)
    return out


def tonemap(rgb, look="aces", exposure=0.0):
    """Scene-referred linear -> display-referred linear.

    `aces` is the Narkowicz ACES fit: the curve games actually ship, contrasty
    with a highlight roll-off that desaturates towards white instead of clipping
    to a flat primary. `punchy` is that plus saturation, which is the stylised
    look. `linear` just clips, for when the output is data rather than a picture.
    """
    numpy = require_numpy()
    x = rgb * (2.0**exposure)
    if look == "linear":
        return numpy.clip(x, 0.0, 1.0)
    fitted = (x * (2.51 * x + 0.03)) / (x * (2.43 * x + 0.59) + 0.14)
    fitted = numpy.clip(fitted, 0.0, 1.0)
    if look == "punchy":
        fitted = saturate(fitted, 1.14)
    return fitted


def saturate(rgb, amount):
    numpy = require_numpy()
    if abs(amount - 1.0) < 1e-6:
        return rgb
    grey = luminance(rgb)[..., None]
    return numpy.clip(grey + (rgb - grey) * amount, 0.0, 1.0)


def contrast(rgb, amount, pivot=0.45):
    numpy = require_numpy()
    if abs(amount - 1.0) < 1e-6:
        return rgb
    return numpy.clip((rgb - pivot) * amount + pivot, 0.0, 1.0)


def vignette(rgb, amount=0.25, softness=0.65):
    """Darken the corners. Costs nothing and focuses the eye on the subject."""
    numpy = require_numpy()
    if amount <= 0.0:
        return rgb
    height, width = rgb.shape[:2]
    ys = numpy.linspace(-1.0, 1.0, height, dtype=numpy.float32)[:, None]
    xs = numpy.linspace(-1.0, 1.0, width, dtype=numpy.float32)[None, :]
    radius = numpy.sqrt(xs * xs + ys * ys) / 1.41421356
    falloff = numpy.clip((radius - softness) / max(1e-6, 1.0 - softness), 0.0, 1.0)
    return rgb * (1.0 - falloff[..., None] * amount)


# --------------------------------------------------------------------------
# backdrops and compositing
# --------------------------------------------------------------------------


def radial_backdrop(width, height, inner, outer, centre_y=0.42, spread=1.05):
    """A radial gradient, brightest behind the subject.

    The single most effective backdrop for an icon: it separates the silhouette
    everywhere at once, where a flat colour separates it only where the subject
    happens to differ in value.
    """
    numpy = require_numpy()
    ys = numpy.linspace(0.0, 1.0, height, dtype=numpy.float32)[:, None]
    xs = numpy.linspace(0.0, 1.0, width, dtype=numpy.float32)[None, :]
    radius = numpy.sqrt((xs - 0.5) ** 2 + (ys - centre_y) ** 2) / max(1e-6, spread * 0.7071)
    t = numpy.clip(radius, 0.0, 1.0)
    t = t * t * (3.0 - 2.0 * t)  # smoothstep — a linear ramp bands visibly
    inner_rgb = numpy.array(inner[:3], dtype=numpy.float32)
    outer_rgb = numpy.array(outer[:3], dtype=numpy.float32)
    return inner_rgb + (outer_rgb - inner_rgb) * t[..., None]


def over(foreground, background_rgb, premultiplied=True):
    """Composite RGBA over an opaque RGB backdrop."""
    numpy = require_numpy()
    alpha = foreground[..., 3:4]
    rgb = foreground[..., :3]
    if not premultiplied:
        rgb = rgb * alpha
    out = numpy.empty_like(foreground)
    out[..., :3] = rgb + background_rgb * (1.0 - alpha)
    out[..., 3] = 1.0
    return out
