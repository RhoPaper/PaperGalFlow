from __future__ import annotations

import unittest

from pgf_adapter_renpy.assets import build_ui_assets, node_frame_border, ui_manifest
from pgf_adapter_renpy.entry import EntryOptions, build_entry_plan
from pgf_adapter_renpy.png import decode_png, is_generated_asset
from pgf_style import preset_tokens, style_tokens


def pixel(image, x: int, y: int) -> tuple[int, int, int, int]:
    base = (y * image.width + x) * 4
    return tuple(image.pixels[base : base + 4])  # type: ignore[return-value]


class AssetGenerationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.tokens = preset_tokens()
        cls.assets = build_ui_assets(cls.tokens)
        cls.by_name = {asset.name: asset for asset in cls.assets}

    def test_expected_assets(self) -> None:
        names = set(self.by_name)
        for name in (
            "pgf_ui/node_read.png",
            "pgf_ui/node_read_hover.png",
            "pgf_ui/node_choice.png",
            "pgf_ui/legend_ending.png",
            "pgf_ui/shadow.png",
            "pgf_ui/bar_shadow.png",
            "pgf_ui/panel_top.png",
            "pgf_ui/panel_bottom.png",
            "pgf_ui/label.png",
            "pgf_ui/button.png",
            "pgf_ui/button_hover.png",
            "pgf_ui/accent_button.png",
            "pgf_ui/accent_button_hover.png",
        ):
            self.assertIn(name, names)
        self.assertEqual(len(names), 25)
        for asset in self.assets:
            self.assertTrue(is_generated_asset(asset.data), asset.name)

    def test_node_corners_are_transparent(self) -> None:
        image = decode_png(self.by_name["pgf_ui/node_read.png"].data)
        self.assertEqual(pixel(image, 0, 0)[3], 0)
        self.assertEqual(pixel(image, image.width - 1, 0)[3], 0)
        self.assertEqual(pixel(image, 0, image.height - 1)[3], 0)
        # The centre is fully opaque and uses the palette fill.
        self.assertEqual(pixel(image, 48, 48)[3], 255)

    def test_node_strip_is_baked_into_the_left_slice(self) -> None:
        image = decode_png(self.by_name["pgf_ui/node_read.png"].data)
        strip = pixel(image, 12, 48)
        expected = self.tokens.palette("read").strip
        self.assertEqual(strip[3], 255)
        self.assertEqual("#%02x%02x%02x" % strip[:3], expected[:7])

    def test_hover_uses_the_hover_fill(self) -> None:
        idle = decode_png(self.by_name["pgf_ui/node_read.png"].data)
        hover = decode_png(self.by_name["pgf_ui/node_read_hover.png"].data)
        self.assertNotEqual(pixel(idle, 48, 48), pixel(hover, 48, 48))

    def test_panel_corners_are_direction_aware(self) -> None:
        top = decode_png(self.by_name["pgf_ui/panel_top.png"].data)
        self.assertEqual(pixel(top, 0, 0)[3], 255)  # square top
        self.assertEqual(pixel(top, 0, top.height - 1)[3], 0)  # rounded bottom
        bottom = decode_png(self.by_name["pgf_ui/panel_bottom.png"].data)
        self.assertEqual(pixel(bottom, 0, 0)[3], 0)
        self.assertEqual(pixel(bottom, 0, bottom.height - 1)[3], 255)

    def test_shadow_fades_out(self) -> None:
        shadow = decode_png(self.by_name["pgf_ui/shadow.png"].data)
        self.assertEqual(pixel(shadow, 0, 0)[3], 0)
        self.assertGreater(pixel(shadow, 48, 48)[3], 40)

    def test_manifest_paths_and_frame(self) -> None:
        manifest = ui_manifest(self.tokens)
        self.assertEqual(manifest["node_read"], "pgf_ui/node_read.png")
        self.assertEqual(manifest["legend_locked"], "pgf_ui/legend_locked.png")
        self.assertGreaterEqual(int(manifest["frame"]), 20)
        self.assertEqual(int(manifest["frame"]), node_frame_border(self.tokens))

    def test_geometry_follows_tokens(self) -> None:
        tokens = style_tokens(corner_radius=22, border_width=3)
        names = {asset.name for asset in build_ui_assets(tokens)}
        self.assertIn("pgf_ui/node_unread.png", names)
        self.assertGreater(node_frame_border(tokens), node_frame_border(self.tokens))

    def test_deterministic(self) -> None:
        other = build_ui_assets(preset_tokens())
        self.assertEqual(
            [(asset.name, asset.data) for asset in self.assets],
            [(asset.name, asset.data) for asset in other],
        )

    def test_entry_button_uses_generated_frame(self) -> None:
        plan = build_entry_plan(self.tokens, None, EntryOptions(screen_size=(1920, 1080)))
        self.assertIn('Frame("pgf_ui/accent_button.png", 20, 20)', plan.file.content)
        self.assertIn('Frame("pgf_ui/accent_button_hover.png", 20, 20)', plan.file.content)


if __name__ == "__main__":
    unittest.main()
