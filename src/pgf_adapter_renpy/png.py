"""A tiny PNG codec used to sample and generate UI assets.

Ren'Py ships UI backgrounds, button images and icons as PNG files inside
``.rpa`` archives.  Sampling their dominant colours gives a much more faithful
palette than the default GUI template, without needing Pillow (which would
break the "pure standard library, Windows friendly" promise).  The encoder at
the bottom of this module lets PaperGalFlow draw its own anti-aliased nine
patch assets for Ren'Py ``Frame`` displayables.

The decoder only handles the common subset: 8/16 bit non-interlaced images with
greyscale, RGB, palette, grey+alpha or RGBA pixels.  Anything outside that
raises :class:`PngError` and the caller simply skips the asset.
"""

from __future__ import annotations

import struct
import zlib
from dataclasses import dataclass

from pgf_core.errors import PgfError
from pgf_style import parse_color

__all__ = [
    "PngError",
    "PngImage",
    "PngColorStats",
    "decode_png",
    "encode_png",
    "color_stats",
    "analyze_png",
    "PngAnalysis",
    "png_size",
]

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
_MAX_PIXELS = 40_000_000
_MARKER_KEY = b"Software"
_MARKER_VALUE = b"PaperGalFlow"


class PngError(PgfError):
    """The asset is not a PNG this module can decode."""


@dataclass(frozen=True)
class PngImage:
    width: int
    height: int
    pixels: bytes  # RGBA, row major, 4 bytes per pixel


@dataclass(frozen=True)
class PngColorStats:
    average: str
    dominant: str
    coverage: float
    width: int
    height: int


def _parse_chunks(data: bytes) -> tuple[dict[str, bytes], list[bytes]]:
    if not data.startswith(PNG_SIGNATURE):
        raise PngError("not a PNG file")
    position = len(PNG_SIGNATURE)
    header: dict[str, bytes] = {}
    idat: list[bytes] = []
    while position + 8 <= len(data):
        length, kind = struct.unpack(">I4s", data[position : position + 8])
        position += 8
        payload = data[position : position + length]
        if len(payload) != length:
            raise PngError("truncated PNG chunk")
        position += length + 4  # skip CRC
        if kind == b"IHDR":
            header["IHDR"] = payload
        elif kind == b"PLTE":
            header["PLTE"] = payload
        elif kind == b"tRNS":
            header["tRNS"] = payload
        elif kind == b"IDAT":
            idat.append(payload)
        elif kind == b"IEND":
            break
        elif kind in (b"gAMA", b"sRGB", b"pHYs", b"iCCP", b"tEXt", b"zTXt", b"iTXt", b"bKGD"):
            continue
        else:
            # Unknown ancillary chunk: ignore, as the PNG spec requires.
            continue
    if "IHDR" not in header or not idat:
        raise PngError("missing IHDR or IDAT chunk")
    return header, idat


def _paeth(a: int, b: int, c: int) -> int:
    p = a + b - c
    pa = abs(p - a)
    pb = abs(p - b)
    pc = abs(p - c)
    if pa <= pb and pa <= pc:
        return a
    if pb <= pc:
        return b
    return c


def _unfilter(raw: bytes, width: int, height: int, channels: int, bit_depth: int) -> bytes:
    """Undo PNG scanline filters and return packed samples."""

    row_bytes = (width * channels * bit_depth + 7) // 8
    bpp = max(1, (channels * bit_depth + 7) // 8)
    expected = height * (row_bytes + 1)
    if len(raw) < expected:
        raise PngError("truncated image data")
    result = bytearray(height * row_bytes)
    previous = bytearray(row_bytes)
    position = 0
    for y in range(height):
        filter_type = raw[position]
        position += 1
        row = bytearray(raw[position : position + row_bytes])
        position += row_bytes
        if filter_type == 1:  # Sub
            for i in range(bpp, row_bytes):
                row[i] = (row[i] + row[i - bpp]) & 0xFF
        elif filter_type == 2:  # Up
            for i in range(row_bytes):
                row[i] = (row[i] + previous[i]) & 0xFF
        elif filter_type == 3:  # Average
            for i in range(row_bytes):
                left = row[i - bpp] if i >= bpp else 0
                row[i] = (row[i] + ((left + previous[i]) >> 1)) & 0xFF
        elif filter_type == 4:  # Paeth
            for i in range(row_bytes):
                left = row[i - bpp] if i >= bpp else 0
                up = previous[i]
                up_left = previous[i - bpp] if i >= bpp else 0
                row[i] = (row[i] + _paeth(left, up, up_left)) & 0xFF
        elif filter_type != 0:
            raise PngError(f"unsupported PNG filter {filter_type}")
        result[y * row_bytes : (y + 1) * row_bytes] = row
        previous = row
    return bytes(result)


def _samples(
    packed: bytes,
    width: int,
    height: int,
    channels: int,
    bit_depth: int,
):
    """Yield tuples of samples per pixel (ints at the PNG bit depth)."""

    row_bytes = (width * channels * bit_depth + 7) // 8
    for y in range(height):
        row = packed[y * row_bytes : (y + 1) * row_bytes]
        if bit_depth == 8:
            for x in range(width):
                base = x * channels
                yield tuple(row[base : base + channels])
        elif bit_depth == 16:
            for x in range(width):
                base = x * channels * 2
                yield tuple(
                    (row[base + 2 * c] << 8) | row[base + 2 * c + 1]
                    for c in range(channels)
                )
        else:
            mask = (1 << bit_depth) - 1
            per_byte = 8 // bit_depth
            values = []
            for byte in row:
                for slot in range(per_byte):
                    shift = 8 - bit_depth * (slot + 1)
                    values.append((byte >> shift) & mask)
            for x in range(width):
                yield (values[x],)


def png_size(data: bytes) -> tuple[int, int]:
    """Return ``(width, height)`` without decoding pixel data."""

    if not data.startswith(PNG_SIGNATURE) or len(data) < 33:
        raise PngError("not a PNG file")
    if data[12:16] != b"IHDR":
        raise PngError("PNG does not start with IHDR")
    width, height = struct.unpack(">II", data[16:24])
    return width, height


def decode_png(data: bytes, max_rows: int | None = None) -> PngImage:
    header, idat = _parse_chunks(data)
    width, height, bit_depth, color_type, compression, filter_method, interlace = struct.unpack(
        ">IIBBBBB", header["IHDR"]
    )
    if max_rows is not None:
        height = max(1, min(height, int(max_rows)))
    if compression != 0 or filter_method != 0:
        raise PngError("unsupported PNG compression/filter method")
    if interlace != 0:
        raise PngError("interlaced PNGs are not supported")
    if width <= 0 or height <= 0 or width * height > _MAX_PIXELS:
        raise PngError("PNG dimensions are out of range")
    channels_by_type = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}
    if color_type not in channels_by_type:
        raise PngError(f"unsupported PNG colour type {color_type}")
    if bit_depth not in (1, 2, 4, 8, 16):
        raise PngError(f"unsupported PNG bit depth {bit_depth}")
    if color_type not in (0, 3) and bit_depth < 8:
        raise PngError("sub-byte samples are only supported for palette/greyscale")

    channels = channels_by_type[color_type]
    palette = header.get("PLTE", b"")
    transparency = header.get("tRNS", b"")

    try:
        raw = zlib.decompress(b"".join(idat))
    except zlib.error as exc:
        raise PngError(f"could not decompress PNG data: {exc}") from exc
    packed = _unfilter(raw, width, height, channels, bit_depth)

    out = bytearray(width * height * 4)
    target = 0
    for samples in _samples(packed, width, height, channels, bit_depth):
        if color_type == 0:  # greyscale
            value = samples[0]
            if bit_depth == 16:
                value >>= 8
            elif bit_depth < 8:
                value = int(value * 255 / ((1 << bit_depth) - 1))
            r = g = b = value
            a = 255
        elif color_type == 2:  # RGB
            r, g, b = samples
            if bit_depth == 16:
                r, g, b = r >> 8, g >> 8, b >> 8
            a = 255
        elif color_type == 3:  # palette
            index = int(samples[0])
            base = index * 3
            if base + 2 >= len(palette):
                r = g = b = 0
            else:
                r, g, b = palette[base], palette[base + 1], palette[base + 2]
            a = transparency[index] if index < len(transparency) else 255
        elif color_type == 4:  # grey + alpha
            value, alpha = samples
            if bit_depth == 16:
                value >>= 8
                alpha >>= 8
            r = g = b = value
            a = alpha
        else:  # RGBA
            r, g, b, a = samples
            if bit_depth == 16:
                r, g, b, a = r >> 8, g >> 8, b >> 8, a >> 8
        out[target] = r
        out[target + 1] = g
        out[target + 2] = b
        out[target + 3] = a
        target += 4
    return PngImage(width, height, bytes(out))


def _hex(r: int, g: int, b: int) -> str:
    return f"#{r:02x}{g:02x}{b:02x}"


def color_stats(data: bytes) -> PngColorStats:
    """Return average/dominant colour and opaque coverage of a PNG."""

    original_width, original_height = png_size(data)
    max_rows = max(1, 900_000 // max(1, original_width))
    image = decode_png(data, max_rows=max_rows)
    pixels = image.pixels
    total = image.width * image.height
    step = max(1, total // 250_000)
    counts: dict[tuple[int, int, int], int] = {}
    bucket_sums: dict[tuple[int, int, int], list[int]] = {}
    sum_r = sum_g = sum_b = 0
    weighted = 0
    opaque = 0
    sampled = 0
    for index in range(0, total, step):
        base = index * 4
        r, g, b, a = pixels[base], pixels[base + 1], pixels[base + 2], pixels[base + 3]
        sampled += 1
        if a < 8:
            continue
        opaque += 1
        sum_r += r * a
        sum_g += g * a
        sum_b += b * a
        weighted += a
        if a >= 128:
            key = (r >> 3, g >> 3, b >> 3)
            counts[key] = counts.get(key, 0) + 1
            bucket = bucket_sums.setdefault(key, [0, 0, 0, 0])
            bucket[0] += 1
            bucket[1] += r
            bucket[2] += g
            bucket[3] += b
    if not weighted:
        return PngColorStats("#00000000", "#00000000", 0.0, original_width, original_height)
    average = _hex(
        int(round(sum_r / weighted)), int(round(sum_g / weighted)), int(round(sum_b / weighted))
    )
    if counts:
        best_key = max(counts, key=counts.get)
        count, reds, greens, blues = bucket_sums[best_key]
        dominant = _hex(
            int(round(reds / count)), int(round(greens / count)), int(round(blues / count))
        )
    else:
        dominant = average
    coverage = opaque / sampled if sampled else 0.0
    return PngColorStats(average, dominant, coverage, original_width, original_height)


# ---------------------------------------------------------------------------
# encoder (used for generated nine patch assets)
# ---------------------------------------------------------------------------


def _chunk(kind: bytes, payload: bytes) -> bytes:
    return (
        struct.pack(">I", len(payload))
        + kind
        + payload
        + struct.pack(">I", zlib.crc32(kind + payload) & 0xFFFFFFFF)
    )


def encode_png(
    width: int,
    height: int,
    pixels: bytes,
    *,
    metadata: dict[str, str] | None = None,
) -> bytes:
    """Encode straight RGBA pixels as an 8 bit, non-interlaced PNG.

    ``metadata`` becomes ``tEXt`` chunks.  PaperGalFlow always writes a
    ``Software=PaperGalFlow`` marker so the installer can prove it owns a
    generated asset before overwriting or deleting it.
    """

    width = int(width)
    height = int(height)
    if width <= 0 or height <= 0:
        raise PngError("PNG dimensions must be positive")
    if width * height > _MAX_PIXELS:
        raise PngError("PNG dimensions are out of range")
    expected = width * height * 4
    if len(pixels) != expected:
        raise PngError(f"expected {expected} RGBA bytes, got {len(pixels)}")

    rows = bytearray(height * (width * 4 + 1))
    source = 0
    target = 0
    for _y in range(height):
        rows[target] = 0  # filter: none
        target += 1
        rows[target : target + width * 4] = pixels[source : source + width * 4]
        source += width * 4
        target += width * 4

    chunks = bytearray(PNG_SIGNATURE)
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    chunks += _chunk(b"IHDR", ihdr)
    entries = {"Software": "PaperGalFlow"}
    if metadata:
        entries.update({str(key): str(value) for key, value in metadata.items()})
    for key, value in entries.items():
        key_bytes = key.encode("latin-1", "replace")
        value_bytes = value.encode("latin-1", "replace")
        chunks += _chunk(b"tEXt", key_bytes + b"\x00" + value_bytes)
    chunks += _chunk(b"IDAT", zlib.compress(bytes(rows), 9))
    chunks += _chunk(b"IEND", b"")
    return bytes(chunks)


def is_generated_asset(data: bytes) -> bool:
    """True when *data* is a PaperGalFlow generated PNG (marker in header)."""

    return data.startswith(PNG_SIGNATURE) and _MARKER_KEY + b"\x00" + _MARKER_VALUE in data[:2048]


# ---------------------------------------------------------------------------
# UI region analysis (gradient / translucency / nine-patch hints)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PngAnalysis:
    """Region aware colour analysis of one UI asset."""

    width: int
    height: int
    average: str
    dominant: str
    center: str
    edge: str
    coverage: float
    gradient: bool
    gradient_top: str
    gradient_bottom: str
    insets: tuple[int, int, int, int] = (0, 0, 0, 0)
    border_width: int = 0
    corner_radius: int = 0
    corner_alpha: float = 1.0
    opacity: float = 1.0

    @property
    def translucent(self) -> bool:
        return self.coverage < 0.98 or self.opacity < 0.98

    def to_dict(self) -> dict[str, object]:
        return {
            "width": self.width,
            "height": self.height,
            "average": self.average,
            "dominant": self.dominant,
            "center": self.center,
            "edge": self.edge,
            "coverage": round(self.coverage, 3),
            "gradient": self.gradient,
            "gradient_top": self.gradient_top,
            "gradient_bottom": self.gradient_bottom,
            "insets": list(self.insets),
            "border_width": self.border_width,
            "corner_radius": self.corner_radius,
            "corner_alpha": round(self.corner_alpha, 3),
            "opacity": round(self.opacity, 3),
            "translucent": self.translucent,
        }


def _rgba_at(pixels: bytes, width: int, x: int, y: int) -> tuple[int, int, int, int]:
    base = (y * width + x) * 4
    return pixels[base], pixels[base + 1], pixels[base + 2], pixels[base + 3]


def _weighted_color(samples: list[tuple[int, int, int, int]]) -> str:
    total = 0
    reds = greens = blues = 0
    for red, green, blue, alpha in samples:
        if alpha < 8:
            continue
        total += alpha
        reds += red * alpha
        greens += green * alpha
        blues += blue * alpha
    if not total:
        return ""
    return _hex(int(round(reds / total)), int(round(greens / total)), int(round(blues / total)))


def _color_distance(first: tuple[int, int, int, int], second: tuple[int, int, int, int]) -> int:
    return max(abs(first[index] - second[index]) for index in range(3))


def _side_run(
    pixels: bytes,
    width: int,
    height: int,
    side: str,
) -> tuple[int, int]:
    """Return ``(run, max_run)`` of the uniform edge band on one side."""

    limit = max(1, min(width, height) // 4)
    if side == "left":
        points = [(x, height // 2) for x in range(limit)]
    elif side == "right":
        points = [(width - 1 - x, height // 2) for x in range(limit)]
    elif side == "top":
        points = [(width // 2, y) for y in range(limit)]
    else:
        points = [(width // 2, height - 1 - y) for y in range(limit)]
    first = _rgba_at(pixels, width, *points[0])
    if first[3] < 16:
        count = 0
        for point in points:
            if _rgba_at(pixels, width, *point)[3] < 16:
                count += 1
            else:
                break
        return count, limit
    count = 0
    for point in points:
        value = _rgba_at(pixels, width, *point)
        if value[3] < 16 or _color_distance(first, value) > 28:
            break
        count += 1
    return count, limit


def _corner_radius(pixels: bytes, width: int, height: int) -> int:
    """Estimate a rounded corner from transparent pixels, if present."""

    if _rgba_at(pixels, width, 0, 0)[3] > 64:
        return 0
    horizontal = 0
    for x in range(min(width, height) // 2):
        if _rgba_at(pixels, width, x, 0)[3] >= 128:
            horizontal = x
            break
    vertical = 0
    for y in range(min(width, height) // 2):
        if _rgba_at(pixels, width, 0, y)[3] >= 128:
            vertical = y
            break
    return max(horizontal, vertical)


def analyze_png(data: bytes, max_pixels: int = 1_500_000) -> PngAnalysis:
    """Decode a UI asset and report region colours and nine-patch hints."""

    original_width, original_height = png_size(data)
    rows = max(1, min(original_height, max(1, max_pixels // max(1, original_width))))
    image = decode_png(data, max_rows=rows)
    width, height = image.width, image.height
    pixels = image.pixels
    total = width * height
    opaque = 0
    sum_r = sum_g = sum_b = 0
    weighted = 0
    alpha_total = 0
    counts: dict[tuple[int, int, int], int] = {}
    bucket_sums: dict[tuple[int, int, int], list[int]] = {}
    center_samples: list[tuple[int, int, int, int]] = []
    top_samples: list[tuple[int, int, int, int]] = []
    bottom_samples: list[tuple[int, int, int, int]] = []
    edge_samples: list[tuple[int, int, int, int]] = []
    top_band = max(1, height // 8)
    left = int(width * 0.3)
    right = max(left + 1, int(width * 0.7))
    upper = int(height * 0.3)
    lower = max(upper + 1, int(height * 0.7))
    edge = max(1, min(3, min(width, height) // 20))

    for y in range(height):
        for x in range(width):
            red, green, blue, alpha = _rgba_at(pixels, width, x, y)
            alpha_total += alpha
            if alpha < 8:
                continue
            opaque += 1
            sum_r += red * alpha
            sum_g += green * alpha
            sum_b += blue * alpha
            weighted += alpha
            if alpha >= 128:
                key = (red >> 3, green >> 3, blue >> 3)
                counts[key] = counts.get(key, 0) + 1
                bucket = bucket_sums.setdefault(key, [0, 0, 0, 0])
                bucket[0] += 1
                bucket[1] += red
                bucket[2] += green
                bucket[3] += blue
            if left <= x < right and upper <= y < lower:
                center_samples.append((red, green, blue, alpha))
            if y < top_band and left <= x < right:
                top_samples.append((red, green, blue, alpha))
            if y >= height - top_band and left <= x < right:
                bottom_samples.append((red, green, blue, alpha))
            if x < edge or x >= width - edge or y < edge or y >= height - edge:
                edge_samples.append((red, green, blue, alpha))

    if weighted:
        average = _hex(
            int(round(sum_r / weighted)),
            int(round(sum_g / weighted)),
            int(round(sum_b / weighted)),
        )
    else:
        average = "#00000000"
    if counts:
        best = max(counts, key=counts.get)
        count, reds, greens, blues = bucket_sums[best]
        dominant = _hex(
            int(round(reds / count)), int(round(greens / count)), int(round(blues / count))
        )
    else:
        dominant = average

    center = _weighted_color(center_samples) or average
    edge_color = _weighted_color(edge_samples) or dominant
    gradient_top = _weighted_color(top_samples) or average
    gradient_bottom = _weighted_color(bottom_samples) or average
    top_rgba = parse_color(gradient_top) or (0, 0, 0, 0)
    bottom_rgba = parse_color(gradient_bottom) or (0, 0, 0, 0)
    gradient = _color_distance(top_rgba, bottom_rgba) > 26

    runs = {side: _side_run(pixels, width, height, side) for side in ("left", "top", "right", "bottom")}
    values = [run for run, _limit in runs.values()]
    limits = [limit for _run, limit in runs.values()]
    border_candidates = [run for run in values if 0 < run <= 6 and run < min(limits)]
    border_width = min(border_candidates) if len(border_candidates) == 4 else 0
    radius = _corner_radius(pixels, width, height)
    inset_value = max([radius] + [run for run in values if run < min(limits)])
    insets = (inset_value, inset_value, inset_value, inset_value)
    if border_width:
        # A visible border line sits inside the fixed nine-patch slice.
        insets = tuple(max(inset_value, border_width) for _ in range(4))  # type: ignore[assignment]
    corner_samples = [
        _rgba_at(pixels, width, 0, 0),
        _rgba_at(pixels, width, width - 1, 0),
        _rgba_at(pixels, width, 0, height - 1),
        _rgba_at(pixels, width, width - 1, height - 1),
    ]
    corner_alpha = sum(sample[3] for sample in corner_samples) / 4.0 / 255.0
    return PngAnalysis(
        width=original_width,
        height=original_height,
        average=average,
        dominant=dominant,
        center=center,
        edge=edge_color,
        coverage=opaque / total if total else 0.0,
        gradient=gradient,
        gradient_top=gradient_top,
        gradient_bottom=gradient_bottom,
        insets=insets,  # type: ignore[arg-type]
        border_width=border_width,
        corner_radius=radius,
        corner_alpha=corner_alpha,
        opacity=(alpha_total / total / 255.0) if total else 0.0,
    )
