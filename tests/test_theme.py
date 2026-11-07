from __future__ import annotations

import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

from pgf_core.cli import main as cli_main
from pgf_core.errors import PipelineError
from pgf_core.pipeline import Pipeline, PipelineOptions
from pgf_style import (
    ThemeError,
    apply_theme,
    load_theme,
    preset_tokens,
    theme_document,
    write_theme,
)

from .fake_adapter import FakeAdapter


def write_json(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload), encoding="utf-8")


class ThemeLoadTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)

    def test_load_groups_and_palette(self) -> None:
        path = self.root / "theme.json"
        write_json(
            path,
            {
                "schema": 1,
                "name": "sakura",
                "colors": {"accent": "#ff6688", "panel": "#fff0f4"},
                "typography": {"node_text_size": 26, "font": "Game.ttf"},
                "geometry": {"corner_radius": 20, "border_width": 3},
                "palettes": {"read": {"fill": "#f6dce4", "border": "#ff6688"}},
            },
        )
        theme = load_theme(path)
        self.assertEqual(theme.name, "sakura")
        self.assertEqual(theme.values["accent"], "#ff6688")
        self.assertEqual(theme.values["node_text_size"], 26)
        self.assertEqual(theme.values["corner_radius"], 20)
        self.assertEqual(theme.palettes["read"]["fill"], "#f6dce4")
        self.assertTrue(theme.has_color_changes)

    def test_invalid_theme_errors(self) -> None:
        cases = {
            "missing": None,
            "not_object": [],
            "unknown": {"nope": 1},
            "bad_colour": {"colors": {"accent": "not a colour"}},
            "bad_size": {"geometry": {"corner_radius": "big"}},
            "unknown_group_key": {"colors": {"nope": "#fff"}},
            "unknown_palette": {"palettes": {"bogus": {"fill": "#fff"}}},
            "bad_preset": {"preset": "neon"},
        }
        for name, payload in cases.items():
            path = self.root / f"{name}.json"
            if payload is None:
                path.unlink(missing_ok=True)
            elif name == "not_object":
                path.write_text("[]", encoding="utf-8")
            else:
                write_json(path, payload)
            with self.assertRaises(ThemeError, msg=name):
                load_theme(path)

    def test_malformed_json_and_oversize(self) -> None:
        path = self.root / "bad.json"
        path.write_text("{", encoding="utf-8")
        with self.assertRaises(ThemeError):
            load_theme(path)
        path.write_text("{}", encoding="utf-8")
        with self.assertRaises(ThemeError):
            load_theme(self.root / "missing.json")
        big = self.root / "big.json"
        big.write_text('{"name": "' + "x" * 300_000 + '"}', encoding="utf-8")
        with self.assertRaises(ThemeError):
            load_theme(big)


class ThemeApplyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.base = preset_tokens("paper_dark")

    def test_apply_colours_typography_geometry(self) -> None:
        theme = load_theme(
            self._write(
                {
                    "name": "sakura",
                    "colors": {"accent": "#ff6688", "panel": "#221824"},
                    "typography": {"node_text_size": 26},
                    "geometry": {"corner_radius": 20, "border_width": 3},
                }
            )
        )
        tokens = apply_theme(self.base, theme)
        self.assertEqual(tokens.name, "sakura")
        self.assertEqual(tokens.accent, "#ff6688")
        self.assertEqual(tokens.panel, "#221824")
        self.assertEqual(tokens.node_text_size, 26)
        self.assertEqual(tokens.corner_radius, 20)
        self.assertEqual(tokens.border_width, 3)
        self.assertEqual(tokens.palette("read").border, "#ff6688")
        self.assertTrue(tokens.source.endswith("+theme"))
        self.assertTrue(any("theme sakura" in note for note in tokens.notes))

    def test_palette_override_and_preset(self) -> None:
        theme = load_theme(
            self._write(
                {
                    "name": "light",
                    "preset": "paper_light",
                    "palettes": {"read": {"fill": "#123456", "text": "#ffffff"}},
                }
            )
        )
        tokens = apply_theme(self.base, theme)
        self.assertEqual(tokens.source, "theme")
        self.assertEqual(tokens.panel, preset_tokens("paper_light").panel)
        self.assertEqual(tokens.palette("read").fill, "#123456")
        self.assertEqual(tokens.palette("read").text, "#ffffff")

    def test_document_roundtrip(self) -> None:
        document = theme_document(self.base)
        restored = apply_theme(self.base, document)
        for key in (
            "accent",
            "panel",
            "text",
            "node_text_size",
            "corner_radius",
            "border_width",
            "font",
        ):
            self.assertEqual(getattr(restored, key), getattr(self.base, key), key)
        for state in ("read", "unread", "locked", "ending", "choice", "condition"):
            self.assertEqual(restored.palette(state), self.base.palette(state))

    def test_write_and_reload(self) -> None:
        path = self._tmp_dir() / "nested" / "theme.json"
        write_theme(path, self.base)
        self.assertTrue(path.is_file())
        loaded = load_theme(path)
        self.assertEqual(loaded.name, self.base.name)
        self.assertEqual(loaded.values["accent"], self.base.accent)

    def _tmp_dir(self) -> Path:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        return Path(directory.name)

    def _write(self, payload: object) -> Path:
        path = self._tmp_dir() / "theme.json"
        write_json(path, payload)
        return path


class ThemePipelineTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.theme = self.root / "theme.json"
        write_json(self.theme, {"name": "test", "colors": {"accent": "#ff00aa"}})

    def test_pipeline_applies_theme(self) -> None:
        report = Pipeline(
            FakeAdapter(),
            PipelineOptions(path=self.root, theme_path=str(self.theme)),
        ).run()
        self.assertEqual(report.style.tokens.accent, "#ff00aa")
        self.assertEqual(report.style.tokens.name, "test")
        self.assertTrue(any(outcome.step == "theme" for outcome in report.chains["style"].outcomes))

    def test_pipeline_rejects_bad_theme(self) -> None:
        self.theme.write_text('{"colors": {"accent": "bogus"}}', encoding="utf-8")
        with self.assertRaises(PipelineError):
            Pipeline(
                FakeAdapter(),
                PipelineOptions(path=self.root, theme_path=str(self.theme)),
            ).run()

    def test_cli_theme_template_and_preview(self) -> None:
        template = self.root / "template.json"
        with redirect_stdout(io.StringIO()):
            code = cli_main(["theme", "--preset", "paper_light", "--out", str(template)])
        self.assertEqual(code, 0)
        self.assertTrue(template.is_file())
        self.assertEqual(load_theme(template).name, "paper_light")

        output = self.root / "preview.html"
        env = {"PGF_ADAPTERS": "tests.fake_adapter:FakeAdapter"}
        with mock.patch.dict(os.environ, env):
            with redirect_stdout(io.StringIO()):
                code = cli_main(
                    [
                        "preview",
                        str(self.root),
                        "--adapter",
                        "fake",
                        "--theme",
                        str(self.theme),
                        "--out",
                        str(output),
                    ]
                )
        self.assertEqual(code, 0)
        html = output.read_text(encoding="utf-8")
        self.assertIn("#ff00aa", html)


if __name__ == "__main__":
    unittest.main()
