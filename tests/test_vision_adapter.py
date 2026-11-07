from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from pgf_adapter_renpy.adapter import RenPyAdapter
from pgf_core.errors import AdapterError

from .test_png import make_png
from .test_style_probe import GUI_RPY, SCREENS_RPY


def vision_transport(url, headers, body, timeout):
    content = json.dumps(
        {
            "colors": {
                "accent": "#ff6699",
                "panel": "#fff0f5",
                "text": "#33202a",
            },
            "geometry": {"corner_radius": 20, "border_width": 3},
            "confidence": 0.9,
            "notes": ["pastel dialogue box"],
        }
    )
    return json.dumps({"choices": [{"message": {"content": content}}]}).encode()


class VisionAdapterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._tmp = tempfile.TemporaryDirectory()
        root = Path(cls._tmp.name)
        cls.root = root
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
        cls.shot = root / "shot.png"
        cls.shot.write_bytes(make_png(8, 8, [(240, 240, 240, 255)] * 64))
        cls.adapter = RenPyAdapter()
        cls.info = cls.adapter.detect(root)
        assert cls.info is not None

    @classmethod
    def tearDownClass(cls) -> None:
        cls.adapter.close()
        cls._tmp.cleanup()

    def vision_options(self) -> dict[str, object]:
        return {
            "endpoint": "https://example.test/v1/chat/completions",
            "model": "vision-1",
            "transport": vision_transport,
        }

    def test_build_style_fuses_vision(self) -> None:
        with mock.patch.dict(
            os.environ,
            {"PGF_VISION_ENDPOINT": "", "PGF_VISION_MODEL": "", "PGF_VISION_API_KEY": ""},
            clear=False,
        ):
            result = self.adapter.build_style(
                self.info,
                screenshots=(self.shot,),
                vision_options=self.vision_options(),
            )
        self.assertTrue(result.tokens.source.endswith("+vision"))
        self.assertGreaterEqual(result.tokens.corner_radius, 16)
        self.assertEqual(result.tokens.border_width, 3)
        self.assertIn("vision", result.evidence)
        self.assertTrue(any("vision vision-1" in note for note in result.notes))
        self.assertEqual(result.warnings, [])

    def test_screenshots_without_backend_only_warns(self) -> None:
        with mock.patch.dict(
            os.environ,
            {"PGF_VISION_ENDPOINT": "", "PGF_VISION_MODEL": "", "PGF_VISION_API_KEY": ""},
            clear=False,
        ):
            result = self.adapter.build_style(
                self.info,
                screenshots=(self.shot,),
                vision_options={},
            )
        self.assertFalse(result.tokens.source.endswith("+vision"))
        self.assertTrue(any("not configured" in warning for warning in result.warnings))
        self.assertNotIn("vision", result.evidence)

    def test_screenshot_style_chain(self) -> None:
        result = self.adapter.screenshot_style(
            self.info,
            screenshots=(self.shot,),
            vision_options=self.vision_options(),
            preset="paper_light",
        )
        assert result is not None
        self.assertEqual(result.tokens.source, "preset+vision")
        self.assertEqual(result.tokens.corner_radius, 20)
        self.assertIn("vision", result.evidence)
        self.assertIsNone(self.adapter.screenshot_style(self.info))

    def test_screenshot_style_requires_backend(self) -> None:
        with mock.patch.dict(
            os.environ,
            {"PGF_VISION_ENDPOINT": "", "PGF_VISION_MODEL": "", "PGF_VISION_API_KEY": ""},
            clear=False,
        ):
            with self.assertRaises(AdapterError):
                self.adapter.screenshot_style(
                    self.info, screenshots=(self.shot,), vision_options={}
                )


if __name__ == "__main__":
    unittest.main()
