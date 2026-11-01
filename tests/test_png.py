from __future__ import annotations

import struct
import unittest
import zlib

from pgf_adapter_renpy.png import PngError, color_stats, decode_png

from .game_paths import game1_dir, has_game1


def chunk(kind: bytes, payload: bytes) -> bytes:
    return (
        struct.pack(">I", len(payload))
        + kind
        + payload
        + struct.pack(">I", zlib.crc32(kind + payload) & 0xFFFFFFFF)
    )


def make_png(
    width: int,
    height: int,
    pixels: list[tuple[int, ...]],
    color_type: int = 6,
    bit_depth: int = 8,
    palette: bytes = b"",
    trns: bytes = b"",
) -> bytes:
    channels = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}[color_type]
    rows = bytearray()
    for y in range(height):
        rows.append(0)  # filter type 0
        for x in range(width):
            pixel = pixels[y * width + x]
            for value in pixel[:channels]:
                if bit_depth == 8:
                    rows.append(value & 0xFF)
                elif bit_depth == 16:
                    rows.extend(struct.pack(">H", value))
                else:  # pragma: no cover - helper only uses 8/16
                    raise ValueError(bit_depth)
    ihdr = struct.pack(">IIBBBBB", width, height, bit_depth, color_type, 0, 0, 0)
    parts = [b"\x89PNG\r\n\x1a\n", chunk(b"IHDR", ihdr)]
    if palette:
        parts.append(chunk(b"PLTE", palette))
    if trns:
        parts.append(chunk(b"tRNS", trns))
    parts.append(chunk(b"IDAT", zlib.compress(bytes(rows), 9)))
    parts.append(chunk(b"IEND", b""))
    return b"".join(parts)


class PngDecodeTests(unittest.TestCase):
    def test_rgba(self) -> None:
        data = make_png(2, 1, [(255, 0, 0, 255), (0, 0, 255, 128)])
        image = decode_png(data)
        self.assertEqual((image.width, image.height), (2, 1))
        self.assertEqual(image.pixels[:4], bytes([255, 0, 0, 255]))
        self.assertEqual(image.pixels[4:], bytes([0, 0, 255, 128]))

    def test_rgb(self) -> None:
        data = make_png(1, 1, [(10, 20, 30)], color_type=2)
        image = decode_png(data)
        self.assertEqual(image.pixels, bytes([10, 20, 30, 255]))

    def test_greyscale(self) -> None:
        data = make_png(2, 1, [(0,), (255,)], color_type=0)
        image = decode_png(data)
        self.assertEqual(image.pixels[0:4], bytes([0, 0, 0, 255]))
        self.assertEqual(image.pixels[4:8], bytes([255, 255, 255, 255]))

    def test_grey_alpha(self) -> None:
        data = make_png(1, 1, [(100, 150)], color_type=4)
        image = decode_png(data)
        self.assertEqual(image.pixels, bytes([100, 100, 100, 150]))

    def test_palette(self) -> None:
        palette = bytes([255, 0, 0, 0, 255, 0])
        data = make_png(2, 1, [(0,), (1,)], color_type=3, palette=palette)
        image = decode_png(data)
        self.assertEqual(image.pixels[0:4], bytes([255, 0, 0, 255]))
        self.assertEqual(image.pixels[4:8], bytes([0, 255, 0, 255]))

    def test_palette_transparency(self) -> None:
        palette = bytes([255, 0, 0, 0, 255, 0])
        data = make_png(2, 1, [(0,), (1,)], color_type=3, palette=palette, trns=b"\x00\xff")
        image = decode_png(data)
        self.assertEqual(image.pixels[3], 0)
        self.assertEqual(image.pixels[7], 255)

    def test_16_bit(self) -> None:
        data = make_png(1, 1, [(0xFF80, 0x0080, 0x10FF, 0xFFFF)], bit_depth=16)
        image = decode_png(data)
        self.assertEqual(image.pixels, bytes([0xFF, 0x00, 0x10, 0xFF]))

    def test_garbage_and_truncated(self) -> None:
        with self.assertRaises(PngError):
            decode_png(b"not a png")
        data = make_png(2, 2, [(0, 0, 0, 0)] * 4)
        with self.assertRaises(PngError):
            decode_png(data[:-20])

    def test_interlaced_rejected(self) -> None:
        data = bytearray(make_png(1, 1, [(0, 0, 0, 0)]))
        ihdr_offset = len(b"\x89PNG\r\n\x1a\n") + 8
        data[ihdr_offset + 12] = 1
        with self.assertRaises(PngError):
            decode_png(bytes(data))


class ColorStatsTests(unittest.TestCase):
    def test_solid_red(self) -> None:
        data = make_png(4, 4, [(255, 0, 0, 255)] * 16)
        stats = color_stats(data)
        self.assertEqual(stats.average, "#ff0000")
        self.assertEqual(stats.dominant, "#ff0000")
        self.assertAlmostEqual(stats.coverage, 1.0)
        self.assertEqual((stats.width, stats.height), (4, 4))

    def test_transparency_coverage(self) -> None:
        pixels = [(255, 0, 0, 255)] * 2 + [(0, 0, 0, 0)] * 2
        stats = color_stats(make_png(2, 2, pixels))
        self.assertAlmostEqual(stats.coverage, 0.5)
        self.assertEqual(stats.average, "#ff0000")

    def test_fully_transparent(self) -> None:
        stats = color_stats(make_png(1, 1, [(0, 0, 0, 0)]))
        self.assertEqual(stats.coverage, 0.0)
        self.assertTrue(stats.average.endswith("00"))


@unittest.skipUnless(has_game1(), "test game 1 is not installed")
class RealAssetTests(unittest.TestCase):
    def test_sample_real_quick_button(self) -> None:
        from pgf_adapter_renpy.archive import GameArchive

        with GameArchive.open(game1_dir() / "game") as archive:
            data = archive.read("gui/custom2/dialog/dialog_menu_auto_normal.png")
        stats = color_stats(data)
        self.assertGreater(stats.width, 0)
        self.assertGreater(stats.height, 0)
        self.assertGreater(stats.coverage, 0.05)
        self.assertRegex(stats.average, r"^#[0-9a-f]{6}$")


if __name__ == "__main__":
    unittest.main()
