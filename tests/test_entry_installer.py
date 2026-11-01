from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from pgf_adapter_renpy.entry import EntryOptions, build_entry_plan
from pgf_adapter_renpy.installer import (
    InstallError,
    install_files,
    read_manifest,
    resolve_game_dir,
    static_check,
    uninstall_files,
    verify_install,
)
from pgf_adapter_renpy.screen_emit import GeneratedFile
from pgf_adapter_renpy.style_probe import QuickButton, QuickMenuProbe
from pgf_style import preset_tokens


def quick_menu(source: str = "", has_source: bool = False) -> QuickMenuProbe:
    return QuickMenuProbe(
        screen_name="quick_menu",
        found=True,
        has_source=has_source,
        source=source,
        parameters="()",
        buttons=[
            QuickButton(100, 300, 120, 50, "gui/q.png"),
            QuickButton(240, 300, 120, 50, "gui/q2.png"),
        ],
        screen_size=(1280, 720),
    )


class EntryPlanTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tokens = preset_tokens("paper_light")

    def test_overlay_mode_has_hotkey(self) -> None:
        plan = build_entry_plan(self.tokens, quick_menu(has_source=False), EntryOptions(screen_size=(1280, 720)))
        self.assertEqual(plan.mode, "overlay_button")
        content = plan.file.content
        self.assertIn("screen pgf_quick_button", content)
        self.assertIn("screen pgf_hotkey", content)
        self.assertIn("config.keymap", content)
        self.assertIn('action ShowMenu("pgf_flowchart")', content)
        self.assertEqual(static_check([plan.file]), [])
        x, y = plan.position
        self.assertGreaterEqual(x, 0)
        self.assertGreaterEqual(y, 0)
        self.assertLessEqual(x + plan.size[0], 1280)
        self.assertLessEqual(y + plan.size[1], 720)

    def test_source_patch_mode(self) -> None:
        source = '    imagebutton:\n        xpos 100\n        ypos 300\n        idle "gui/q.png"\n'
        plan = build_entry_plan(
            self.tokens,
            quick_menu(source=source, has_source=True),
            EntryOptions(screen_size=(1280, 720)),
        )
        self.assertEqual(plan.mode, "quick_menu_patch")
        content = plan.file.content
        self.assertIn("screen pgf_quick_menu_base():", content)
        self.assertIn("screen quick_menu():", content)
        self.assertIn("use pgf_quick_menu_base", content)
        self.assertIn("init offset = 999", content)
        self.assertIn('imagebutton:', content)
        self.assertEqual(static_check([plan.file]), [])

    def test_force_overlay_wins(self) -> None:
        plan = build_entry_plan(
            self.tokens,
            quick_menu(source="    textbutton 'x' action NullAction()\n", has_source=True),
            EntryOptions(force_mode="overlay_button", screen_size=(1280, 720)),
        )
        self.assertEqual(plan.mode, "overlay_button")

    def test_missing_quick_menu_uses_overlay(self) -> None:
        plan = build_entry_plan(self.tokens, None, EntryOptions(screen_size=(1920, 1080)))
        self.assertEqual(plan.mode, "overlay_button")
        x, y = plan.position
        self.assertLessEqual(x + plan.size[0], 1920)
        self.assertLessEqual(y + plan.size[1], 1080)


class InstallerTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.game = self.root / "game"
        self.game.mkdir()

    def make_files(self):
        flowchart = (
            "# PaperGalFlow test screen\n"
            "PGF_NODES = [('start', 'entry', '开始', '', 'start', 0, 0, 10, 10)]\n"
            "screen pgf_flowchart():\n"
            "    text \"chart\"\n"
        )
        hook = (
            "# PaperGalFlow test hook\n"
            "screen pgf_quick_button():\n"
            "    textbutton \"流程图\" action ShowMenu(\"pgf_flowchart\")\n"
        )
        return [
            GeneratedFile("pgf_flowchart_screen.rpy", flowchart, "screen"),
            GeneratedFile("pgf_menu_hook.rpy", hook, "entry"),
        ]

    def test_install_manifest_and_verify(self) -> None:
        report = install_files(self.game, self.make_files(), meta={"entry_mode": "overlay_button"})
        self.assertTrue(report.ok, report.errors)
        self.assertEqual(sorted(report.written), ["pgf_flowchart_screen.rpy", "pgf_menu_hook.rpy"])
        manifest = read_manifest(self.game)
        self.assertIsNotNone(manifest)
        assert manifest is not None
        self.assertEqual(manifest["entry_mode"], "overlay_button")
        self.assertEqual(verify_install(self.game), [])

    def test_refuses_unmarked_existing_file(self) -> None:
        (self.game / "pgf_flowchart_screen.rpy").write_text("hand written\n", encoding="utf-8")
        report = install_files(self.game, self.make_files())
        self.assertFalse(report.ok)
        self.assertTrue(any("not created by PaperGalFlow" in error for error in report.errors))

    def test_force_overwrites(self) -> None:
        (self.game / "pgf_flowchart_screen.rpy").write_text("hand written\n", encoding="utf-8")
        report = install_files(self.game, self.make_files(), force=True)
        self.assertTrue(report.ok, report.errors)
        self.assertIn("PaperGalFlow", (self.game / "pgf_flowchart_screen.rpy").read_text())

    def test_uninstall_removes_compiled_companion(self) -> None:
        install_files(self.game, self.make_files())
        (self.game / "pgf_flowchart_screen.rpyc").write_bytes(b"RENPY RPC2" + b"\x00" * 32)
        report = uninstall_files(self.game)
        self.assertTrue(report.ok, report.errors)
        self.assertFalse((self.game / "pgf_flowchart_screen.rpy").exists())
        self.assertFalse((self.game / "pgf_flowchart_screen.rpyc").exists())
        self.assertFalse((self.game / "pgf_manifest.json").exists())

    def test_uninstall_keeps_modified_file_without_force(self) -> None:
        install_files(self.game, self.make_files())
        path = self.game / "pgf_flowchart_screen.rpy"
        path.write_text(path.read_text() + "\n# user edit\n", encoding="utf-8")
        report = uninstall_files(self.game)
        self.assertTrue(path.exists())
        self.assertTrue(any("modified since install" in warning for warning in report.warnings))
        self.assertTrue((self.game / "pgf_manifest.json").exists())
        report = uninstall_files(self.game, force=True)
        self.assertTrue(report.ok, report.errors)
        self.assertFalse(path.exists())
        self.assertFalse((self.game / "pgf_manifest.json").exists())

    def test_dry_run_writes_nothing(self) -> None:
        report = install_files(self.game, self.make_files(), dry_run=True)
        self.assertTrue(report.ok)
        self.assertFalse((self.game / "pgf_flowchart_screen.rpy").exists())
        self.assertIsNone(read_manifest(self.game))

    def test_static_check_rejects_bad_name(self) -> None:
        problems = static_check([GeneratedFile("../evil.rpy", "x\n")])
        self.assertTrue(problems)

    def test_resolve_game_dir(self) -> None:
        self.assertEqual(resolve_game_dir(self.game), self.game.resolve())
        self.assertEqual(resolve_game_dir(self.root), self.game.resolve())
        with self.assertRaises(InstallError):
            resolve_game_dir(self.root / "nope")

    def test_manifest_json(self) -> None:
        install_files(self.game, self.make_files())
        data = json.loads((self.game / "pgf_manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(data["tool"], "PaperGalFlow")
        self.assertEqual(len(data["files"]), 2)
        self.assertTrue(data["files"][0]["sha256"])


if __name__ == "__main__":
    unittest.main()
