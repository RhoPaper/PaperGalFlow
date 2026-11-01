"""A tiny PNG decoder used to sample colours from a game's own UI assets.

Ren'Py ships UI backgrounds, button images and icons as PNG files inside
``.rpa`` archives.  Sampling their dominant colours gives a much more faithful
palette than the default GUI template, without needing Pillow (which would
break the "pure standard library, Windows friendly" promise).

Only the common subset is implemented: 8/16 bit non-interlaced images with
greyscale, RGB, palette, grey+alpha or RGBA pixels.  Anything outside that
raises :class:`PngError` and the caller simply skips the asset.
"""

from __future__ import annotations

import struct
import zlib
from dataclasses import dataclass

from pgf_core.errors import PgfError

__all__ = ["PngError", "PngImage", "PngColorStats", "decode_png", "color_stats", "png_size"]

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
_MAX_PIXELS = 40_000_000


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
