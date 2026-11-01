from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from pgf_adapter_renpy.archive import GameArchive
from pgf_adapter_renpy.style_probe import probe_style
from pgf_style import tokens_from_evidence

from .game_paths import game1_dir, game2_dir, has_game1, has_game2
from .test_png import make_png

GUI_RPY = '''\
init python:
    gui.init(1280, 720)

define gui.accent_color = "#3366ff"
define gui.text_color = "#202020"
define gui.interface_text_size = 32
define gui.title_text_size = 64
define gui.text_font = "GameFont.ttf"
define gui.game_menu_background = "ui/menu_bg.png"

style choice_button:
    background Frame("ui/option_bg.png", 4, 4)
'''

SCREENS_RPY = '''\
screen quick_menu():
    imagebutton:
        xpos 100
        ypos 300
        idle "ui/quick_normal.png"
        hover "ui/quick_hover.png"
        action ShowMenu("save")

screen say(who, what):
    use quick_menu
'''


class SyntheticProbeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._tmp = tempfile.TemporaryDirectory()
        root = Path(cls._tmp.name)
        game = root / "game"
        (game / "ui").mkdir(parents=True)
        (game / "gui.rpy").write_text(GUI_RPY, encoding="utf-8")
        (game / "screens.rpy").write_text(SCREENS_RPY, encoding="utf-8")
        (game / "ui" / "quick_normal.png").write_bytes(
            make_png(64, 24, [(0, 200, 220, 255)] * (64 * 24))
        )
        (game / "ui" / "quick_hover.png").write_bytes(
            make_png(64, 24, [(255, 120, 40, 255)] * (64 * 24))
        )
        (game / "ui" / "option_bg.png").write_bytes(
            make_png(200, 50, [(250, 235, 245, 255)] * (200 * 50))
        )
        (game / "ui" / "menu_bg.png").write_bytes(
            make_png(64, 36, [(30, 40, 60, 255)] * (64 * 36))
        )
        cls.root = root
        cls.game = game
        with GameArchive.open(game) as archive:
            cls.scripts = list(archive.parse_all().values())
            cls.result = probe_style(cls.scripts, archive)
        cls.tokens = tokens_from_evidence(cls.result.evidence)

    @classmethod
    def tearDownClass(cls) -> None:
        cls._tmp.cleanup()

    def test_evidence_values(self) -> None:
        evidence = self.result.evidence
        self.assertEqual(evidence.screen_size, (1280, 720))
        self.assertEqual(evidence.fonts["text"], "GameFont.ttf")
        self.assertEqual(evidence.sizes["interface_text"], 32)
        self.assertEqual(evidence.colors["accent"], "#3366ff")
        self.assertEqual(evidence.background_image, "ui/menu_bg.png")

    def test_samples_and_panel(self) -> None:
        names = {sample.name for sample in self.result.evidence.ui_samples}
        self.assertIn("quick_icon", names)
        self.assertIn("panel", names)
        self.assertIn("option_bg", names)
        panel = next(sample for sample in self.result.evidence.ui_samples if sample.name == "panel")
        self.assertEqual(panel.color, "#faeBF5".upper().lower())
        self.assertEqual(panel.width, 200)
        self.assertEqual(panel.height, 50)

    def test_quick_menu_probe(self) -> None:
        quick = self.result.quick_menu
        self.assertIsNotNone(quick)
        assert quick is not None
        self.assertTrue(quick.found)
        self.assertTrue(quick.has_source)
        self.assertEqual(quick.button_count, 1)
        self.assertEqual(quick.buttons[0].x, 100)
        self.assertEqual(quick.buttons[0].y, 300)
        self.assertEqual(quick.buttons[0].width, 64)
        self.assertTrue(quick.used_by_say)

    def test_placement_inside_screen(self) -> None:
        quick = self.result.quick_menu
        assert quick is not None
        x, y = quick.placement(150, 50)
        self.assertGreaterEqual(x, 0)
        self.assertGreaterEqual(y, 0)
        self.assertLessEqual(x + 150, 1280)
        self.assertLessEqual(y + 50, 720)

    def test_tokens_follow_evidence(self) -> None:
        self.assertEqual(self.tokens.font, "GameFont.ttf")
        self.assertEqual(self.tokens.background_image, "ui/menu_bg.png")
        self.assertGreaterEqual(self.tokens.confidence, 0.5)
        self.assertEqual(self.tokens.source, "game+assets")
        # Light UI panel => light theme with dark text.
        self.assertGreater(self.tokens.background[1:3], "80")


@unittest.skipUnless(has_game1(), "test game 1 is not installed")
class RealGame1ProbeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        with GameArchive.open(game1_dir() / "game") as archive:
            cls.result = probe_style(list(archive.parse_all().values()), archive)
        cls.tokens = tokens_from_evidence(cls.result.evidence)

    def test_quick_menu(self) -> None:
        quick = self.result.quick_menu
        assert quick is not None
        self.assertTrue(quick.found)
        self.assertEqual(quick.button_count, 7)
        self.assertFalse(quick.has_source)
        self.assertEqual(quick.screen_size, (2560, 1440))
        self.assertTrue(quick.bbox)
        x, y = quick.placement(150, 60)
        self.assertLess(x + 150, 2560)
        self.assertLess(y + 60, 1440)

    def test_sampled_panel(self) -> None:
        panel = next(
            (sample for sample in self.result.evidence.ui_samples if sample.name == "panel"),
            None,
        )
        self.assertIsNotNone(panel)
        self.assertTrue(panel.average.startswith("#"))
        self.assertEqual(self.tokens.font, "ChillRoundGothic_Medium.ttf")
        self.assertEqual(self.tokens.node_text_size, 24)

    def test_font_and_screen_size(self) -> None:
        self.assertEqual(self.result.evidence.screen_size, (2560, 1440))
        self.assertIn("gui/", self.tokens.background_image)


@unittest.skipUnless(has_game2(), "test game 2 is not installed")
class RealGame2ProbeTests(unittest.TestCase):
    def test_quick_menu_and_tokens(self) -> None:
        with GameArchive.open(game2_dir() / "game") as archive:
            result = probe_style(list(archive.parse_all().values()), archive)
        tokens = tokens_from_evidence(result.evidence)
        self.assertIsNotNone(result.quick_menu)
        assert result.quick_menu is not None
        self.assertTrue(result.quick_menu.found)
        self.assertGreaterEqual(result.quick_menu.button_count, 6)
        self.assertEqual(result.evidence.screen_size, (1920, 1080))
        self.assertEqual(tokens.source, "game+assets")
        self.assertTrue(result.evidence.ui_samples)


if __name__ == "__main__":
    unittest.main()
