from __future__ import annotations

import struct
import unittest
import zlib

from pgf_adapter_renpy.png import (
    PngError,
    analyze_png,
    color_stats,
    decode_png,
    encode_png,
    is_generated_asset,
)

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


class PngEncodeTests(unittest.TestCase):
    def test_roundtrip_rgba(self) -> None:
        pixels = bytes(
            [255, 0, 0, 255, 0, 255, 0, 128, 0, 0, 255, 0, 12, 34, 56, 255]
        )
        data = encode_png(2, 2, pixels)
        image = decode_png(data)
        self.assertEqual((image.width, image.height), (2, 2))
        self.assertEqual(image.pixels, pixels)
        self.assertTrue(is_generated_asset(data))

    def test_metadata_and_marker(self) -> None:
        data = encode_png(1, 1, bytes([1, 2, 3, 4]), metadata={"Comment": "hello"})
        self.assertIn(b"hello", data)
        self.assertIn(b"PaperGalFlow", data[:2048])
        self.assertFalse(is_generated_asset(data.replace(b"PaperGalFlow", b"SomethingElse")))

    def test_rejects_bad_dimensions(self) -> None:
        with self.assertRaises(PngError):
            encode_png(0, 1, b"")
        with self.assertRaises(PngError):
            encode_png(2, 2, b"\x00" * 4)


class RegionAnalysisTests(unittest.TestCase):
    def test_gradient_uses_center_region(self) -> None:
        width, height = 40, 40
        rows = []
        for y in range(height):
            value = int(round(255 * (1 - y / (height - 1))))
            rows.extend([value, value, value, 255] * width)
        analysis = analyze_png(encode_png(width, height, bytes(rows)))
        self.assertTrue(analysis.gradient)
        self.assertLess(
            int(analysis.gradient_bottom[1:3], 16),
            int(analysis.gradient_top[1:3], 16),
        )
        self.assertEqual(analysis.coverage, 1.0)
        # The centre band sits halfway through the gradient, not at either end.
        self.assertNotEqual(analysis.center, analysis.gradient_top)
        self.assertNotEqual(analysis.center, analysis.gradient_bottom)

    def test_translucent_panel(self) -> None:
        pixels = bytes([250, 240, 230, 128]) * 16
        analysis = analyze_png(encode_png(4, 4, pixels))
        self.assertAlmostEqual(analysis.coverage, 1.0)
        self.assertAlmostEqual(analysis.opacity, 0.502, places=2)
        self.assertEqual(analysis.center, "#faf0e6")
        self.assertTrue(analysis.translucent)

    def test_nine_patch_hints_from_generated_asset(self) -> None:
        from pgf_adapter_renpy.assets import build_ui_assets
        from pgf_style import preset_tokens

        assets = {asset.name: asset for asset in build_ui_assets(preset_tokens())}
        analysis = analyze_png(assets["pgf_ui/panel_top.png"].data)
        self.assertEqual((analysis.width, analysis.height), (64, 64))
        self.assertGreaterEqual(analysis.border_width, 1)
        self.assertGreaterEqual(max(analysis.insets), analysis.border_width)
        self.assertLess(analysis.corner_alpha, 1.0)
