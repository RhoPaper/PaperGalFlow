from __future__ import annotations

import json
import unittest

from pgf_style import (
    StyleEvidence,
    StyleTokens,
    UiSample,
    build_theme,
    contrast_ratio,
    contrast_text,
    darken,
    lighten,
    luminance,
    mix,
    normalize_color,
    parse_color,
    preset_tokens,
    tokens_from_evidence,
    with_alpha,
)


class ColorTests(unittest.TestCase):
    def test_parse_hex_forms(self) -> None:
        self.assertEqual(parse_color("#09f"), (0, 153, 255, 255))
        self.assertEqual(parse_color("0099ff"), (0, 153, 255, 255))
        self.assertEqual(parse_color("#0099ff80"), (0, 153, 255, 128))
        self.assertEqual(parse_color("#00000000"), (0, 0, 0, 0))

    def test_parse_quoted_and_tuples(self) -> None:
        self.assertEqual(parse_color("'#ff0000'"), (255, 0, 0, 255))
        self.assertEqual(parse_color((1, 2, 3)), (1, 2, 3, 255))
        self.assertEqual(parse_color([1, 2, 3, 4]), (1, 2, 3, 4))
        self.assertEqual(parse_color("rgb(1, 2, 3)"), (1, 2, 3, 255))
        self.assertIsNone(parse_color("not a colour"))
        self.assertIsNone(parse_color(None))

    def test_normalize_and_alpha(self) -> None:
        self.assertEqual(normalize_color("'#abc'"), "#aabbcc")
        self.assertEqual(normalize_color("bogus", "#000000"), "#000000")
        self.assertEqual(with_alpha("#000000", 0.5), "#00000080")
        self.assertEqual(with_alpha("#000000ff", 0.0), "#00000000")

    def test_mix_lighten_darken(self) -> None:
        self.assertEqual(mix("#000000", "#ffffff", 0.5), "#808080")
        self.assertEqual(lighten("#000000", 1.0), "#ffffff")
        self.assertEqual(darken("#ffffff", 1.0), "#000000")

    def test_contrast(self) -> None:
        self.assertGreater(contrast_ratio("#000000", "#ffffff"), 20)
        self.assertLess(contrast_ratio("#777777", "#888888"), 1.4)
        self.assertEqual(contrast_text("#000000"), "#f4f7fb")
        self.assertEqual(contrast_text("#ffffff"), "#141821")
        self.assertGreater(luminance("#ffffff"), luminance("#000000"))


class TokenTests(unittest.TestCase):
    def test_defaults_have_all_palettes(self) -> None:
        tokens = preset_tokens()
        for key in ("read", "unread", "locked", "ending", "choice", "condition"):
            palette = tokens.palette(key)
            self.assertTrue(palette.fill.startswith("#"))
            self.assertTrue(palette.text.startswith("#"))

    def test_light_preset(self) -> None:
        tokens = preset_tokens("paper_light")
        self.assertEqual(tokens.name, "paper_light")
        self.assertGreater(luminance(tokens.background), 0.7)
        self.assertLess(luminance(tokens.palette("read").text), 0.5)

    def test_roundtrip(self) -> None:
        tokens = preset_tokens()
        restored = StyleTokens.from_dict(tokens.to_dict())
        self.assertEqual(restored.to_dict(), tokens.to_dict())
        self.assertEqual(restored.palette("read"), tokens.palette("read"))

    def test_merged_keeps_palettes(self) -> None:
        tokens = preset_tokens().merged(title_size=50)
        self.assertEqual(tokens.title_size, 50)
        self.assertIn("read", tokens.palettes)


class EvidenceTests(unittest.TestCase):
    def test_evidence_colors_fonts_sizes(self) -> None:
        evidence = StyleEvidence(
            colors={"accent": "'#ff8844'", "text": "'#222222'"},
            fonts={"text": "GameFont.ttf", "name": "NameFont.ttf"},
            sizes={"interface_text": 30, "title": 60},
            screen_size=(1920, 1080),
            background_image="gui/bg.png",
            ui_samples=[UiSample("panel", "x.png", "#f7f3ea", "#f7f3ea", 0.9, 100, 50)],
            sources=["gui.rpy:accent_color"],
        )
        tokens = tokens_from_evidence(evidence)
        self.assertNotEqual(tokens.accent, tokens.panel)
        self.assertGreaterEqual(contrast_ratio(tokens.accent, tokens.panel), 2.2)
        self.assertEqual(tokens.font, "GameFont.ttf")
        self.assertEqual(tokens.font_bold, "NameFont.ttf")
        self.assertEqual(tokens.background_image, "gui/bg.png")
        self.assertEqual(tokens.node_text_size, 22)
        self.assertEqual(tokens.source, "game+assets")
        self.assertGreater(tokens.confidence, 0.5)
        self.assertEqual(tokens.palette("read").border, tokens.accent)

    def test_dark_text_does_not_break_dark_theme(self) -> None:
        evidence = StyleEvidence(colors={"accent": "#00aaff", "text": "#404040"})
        tokens = tokens_from_evidence(evidence)
        self.assertGreater(luminance(tokens.panel), 0.0)
        self.assertGreater(
            contrast_ratio(tokens.text, tokens.panel),
            3.0,
            "node text must stay readable on the chart panel",
        )

    def test_missing_evidence_uses_preset(self) -> None:
        tokens = tokens_from_evidence(None)
        self.assertEqual(tokens.source, "preset")
        self.assertTrue(tokens.notes)

    def test_light_ui_switches_to_light_preset(self) -> None:
        evidence = StyleEvidence(
            colors={"accent": "#b06a4f"},
            ui_samples=[UiSample("panel", "p.png", "#f6f0e4", "#f6f0e4", 1.0, 10, 10)],
        )
        tokens = tokens_from_evidence(evidence)
        self.assertGreater(luminance(tokens.panel), 0.7)
        self.assertLess(luminance(tokens.palette("read").text), 0.5)

    def test_theme_serialisable(self) -> None:
        theme = build_theme(preset_tokens())
        json.dumps(theme.constants)
        style = theme.constants["PGF_STYLE"]
        self.assertEqual(set(style["palettes"]), {"read", "unread", "locked", "ending", "choice", "condition"})
        self.assertIn("style pgf_title_text:", theme.style_blocks)
        self.assertIn("style pgf_node_text:", theme.style_blocks)

    def test_theme_includes_font(self) -> None:
        tokens = tokens_from_evidence(StyleEvidence(fonts={"text": "MyFont.ttf"}))
        theme = build_theme(tokens)
        self.assertIn('font "MyFont.ttf"', theme.style_blocks)


if __name__ == "__main__":
    unittest.main()
