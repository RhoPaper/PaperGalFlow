from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from pgf_adapter_renpy.archive import ArchiveError, GameArchive, ScriptUnit

from .game_paths import game1_dir, has_game1
from .test_rpa import write_rpa

LABEL_A = 'label a:\n    "A"\n    return\n'
LABEL_B = 'label b:\n    "B"\n    return\n'


class SyntheticGameTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.game = self.root / "game"
        self.game.mkdir()

    def test_disk_units(self) -> None:
        (self.game / "script.rpy").write_text(LABEL_A, encoding="utf-8")
        with GameArchive.open(self.game, use_archives=False) as archive:
            units = archive.units()
            self.assertEqual(len(units), 1)
            unit = units[0]
            self.assertEqual(unit.stem, "script")
            self.assertEqual(unit.format, "rpy")
            self.assertEqual(unit.origin, "disk")
            self.assertIn("a", archive.parse_unit(unit).labels())

    def test_archive_units_and_disk_precedence(self) -> None:
        (self.game / "disk.rpy").write_text(LABEL_A, encoding="utf-8")
        write_rpa(
            self.game / "scripts.rpa",
            {
                "arch.rpy": LABEL_B.encode(),
                "disk.rpy": b"label should_not_win:\n    return\n",
                "sub/nested.rpy": LABEL_A.encode(),
            },
        )
        with GameArchive.open(self.game) as archive:
            units = {unit.stem: unit for unit in archive.units()}
            self.assertEqual(units["disk"].origin, "disk")
            self.assertIn("a", archive.parse_unit(units["disk"]).labels())
            self.assertEqual(units["arch"].origin, "archive")
            self.assertEqual(units["sub/nested"].origin, "archive")
            parsed = archive.parse_all()
            self.assertEqual(set(parsed), {"arch", "disk", "sub/nested"})

    def test_source_wins_over_compiled(self) -> None:
        (self.game / "both.rpy").write_text(LABEL_A, encoding="utf-8")
        (self.game / "both.rpyc").write_bytes(b"garbage")
        with GameArchive.open(self.game) as archive:
            unit = archive.units()[0]
            self.assertEqual(unit.format, "rpy")
            self.assertIn("a", archive.parse_unit(unit).labels())

    def test_generated_pgf_files_are_never_game_source(self) -> None:
        (self.game / "script.rpy").write_text(LABEL_A, encoding="utf-8")
        (self.game / "pgf_menu_hook.rpy").write_text(
            "screen quick_menu():\n    text \"generated\"\n", encoding="utf-8"
        )
        with GameArchive.open(self.game, use_archives=False) as archive:
            self.assertEqual([unit.stem for unit in archive.units()], ["script"])
            self.assertIsNone(archive.screen_source("quick_menu"))

    def test_translations_are_excluded(self) -> None:
        (self.game / "tl" / "japanese").mkdir(parents=True)
        (self.game / "tl" / "japanese" / "common.rpy").write_text(LABEL_A, encoding="utf-8")
        (self.game / "script.rpy").write_text(LABEL_B, encoding="utf-8")
        with GameArchive.open(self.game, use_archives=False) as archive:
            self.assertEqual([unit.stem for unit in archive.units()], ["script"])

    def test_broken_script_is_a_warning(self) -> None:
        (self.game / "bad.rpyc").write_bytes(b"not a renpy script")
        with GameArchive.open(self.game, use_archives=False) as archive:
            parsed = archive.parse_all()
            self.assertEqual(parsed, {})
            self.assertTrue(archive.warnings)

    def test_screen_source(self) -> None:
        (self.game / "screens.rpy").write_text(
            "screen quick_menu():\n    text \"hi\"\n", encoding="utf-8"
        )
        with GameArchive.open(self.game, use_archives=False) as archive:
            found = archive.screen_source("quick_menu")
            self.assertIsNotNone(found)
            source, _script = found
            self.assertIn('text "hi"', source)

    def test_asset_names_and_find_assets(self) -> None:
        (self.game / "ui").mkdir()
        (self.game / "ui" / "dialog_bg.png").write_bytes(b"disk")
        write_rpa(
            self.game / "images.rpa",
            {
                "gui/button/choice_idle_background.png": b"arch",
                "tl/japanese/panel.png": b"translation",
                "pgf_ui/node_read.png": b"generated",
            },
        )
        with GameArchive.open(self.game) as archive:
            names = archive.asset_names()
            self.assertIn("ui/dialog_bg.png", names)
            self.assertIn("gui/button/choice_idle_background.png", names)
            self.assertNotIn("tl/japanese/panel.png", names)
            self.assertNotIn("pgf_ui/node_read.png", names)
            self.assertEqual(
                archive.find_assets(("choice",), limit=4),
                ("gui/button/choice_idle_background.png",),
            )
            self.assertEqual(archive.find_assets(("nothing-here",)), ())

    def test_missing_directory(self) -> None:
        with self.assertRaises(ArchiveError):
            GameArchive(self.root / "nope")

    def test_missing_virtual_file(self) -> None:
        with GameArchive.open(self.game, use_archives=False) as archive:
            with self.assertRaises(ArchiveError):
                archive.read("nope.rpy")


@unittest.skipUnless(has_game1(), "test game 1 is not installed")
class RealGameTests(unittest.TestCase):
    def test_units_and_parse(self) -> None:
        with GameArchive.open(game1_dir() / "game") as archive:
            units = archive.units()
            self.assertGreater(len(units), 20)
            stems = {unit.stem for unit in units}
            self.assertIn("scripts/gui", stems)
            self.assertIn("scripts/content/story/demo", stems)
            self.assertTrue(all(unit.format == "rpyc" for unit in units))
            gui = archive.find_script("scripts/gui")
            self.assertIsNotNone(gui)
            self.assertIn("gui.accent_color", gui.defines())

    def test_no_screen_source_for_compiled_game(self) -> None:
        with GameArchive.open(game1_dir() / "game") as archive:
            self.assertIsNone(archive.screen_source("quick_menu"))


if __name__ == "__main__":
    unittest.main()
