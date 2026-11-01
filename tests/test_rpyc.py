from __future__ import annotations

import pickle
import struct
import unittest
import zlib

from pgf_adapter_renpy.rpyc import RPYC2_HEADER, RpycError, decode_rpyc, extract_payload
from pgf_adapter_renpy.script_model import Stmt

from .game_paths import game1_dir, game2_dir, has_game1, has_game2


class _FakeLabel:
    """Picklable stand-in that pretends to be ``renpy.ast.Label``."""


_FakeLabel.__name__ = "Label"
_FakeLabel.__qualname__ = "Label"
_FakeLabel.__module__ = "renpy.ast"


def make_rpyc(metadata: dict, statements: list, *, slots: int = 2) -> bytes:
    """Build a valid RPYC2 container around an arbitrary payload."""

    body = zlib.compress(pickle.dumps((metadata, statements), protocol=4))
    header = bytearray(RPYC2_HEADER)
    header.extend(b"\x00" * (12 * 4))
    records = []
    if slots >= 1:
        records.append((1, len(header), len(body)))
        header.extend(body)
    if slots >= 2:
        records.append((2, len(header), len(body)))
        header.extend(body)
    for index, record in enumerate(records):
        struct.pack_into("<III", header, len(RPYC2_HEADER) + 12 * index, *record)
    return bytes(header)


class ContainerTests(unittest.TestCase):
    def test_prefers_slot_two(self) -> None:
        body1 = zlib.compress(pickle.dumps({"slot": 1}, protocol=4))
        body2 = zlib.compress(pickle.dumps({"slot": 2}, protocol=4))
        header = bytearray(RPYC2_HEADER)
        header.extend(b"\x00" * 24)
        start1 = len(header)
        header.extend(body1)
        start2 = len(header)
        header.extend(body2)
        struct.pack_into("<III", header, len(RPYC2_HEADER), 1, start1, len(body1))
        struct.pack_into("<III", header, len(RPYC2_HEADER) + 12, 2, start2, len(body2))
        payload = extract_payload(bytes(header))
        self.assertEqual(pickle.loads(payload), {"slot": 2})

    def test_legacy_payload(self) -> None:
        payload = zlib.compress(pickle.dumps(({}, []), protocol=4))
        self.assertEqual(extract_payload(payload), zlib.decompress(payload))

    def test_garbage_rejected(self) -> None:
        with self.assertRaises(RpycError):
            extract_payload(b"not an rpyc file")

    def test_missing_slot_rejected(self) -> None:
        header = RPYC2_HEADER + b"\x00" * 36
        with self.assertRaises(RpycError):
            extract_payload(header)


class DecodeTests(unittest.TestCase):
    def test_synthetic_statements(self) -> None:
        import sys
        import types

        fake_renpy = types.ModuleType("renpy")
        fake_ast = types.ModuleType("renpy.ast")
        fake_ast.Label = _FakeLabel
        sys.modules.setdefault("renpy", fake_renpy)
        sys.modules["renpy.ast"] = fake_ast
        try:
            label = _FakeLabel()
            label.__dict__.update(
                _name="start", block=[], filename="script.rpy", linenumber=3
            )
            blob = make_rpyc({"version": 5003000}, [label])
        finally:
            sys.modules.pop("renpy.ast", None)
            sys.modules.pop("renpy", None)
        script = decode_rpyc(blob, "script.rpyc")
        self.assertIn("start", script.labels())

    def test_evil_pickle_is_inert(self) -> None:
        # A pickle that references builtins.eval must not expose a callable.
        blob = make_rpyc({"version": 1}, [eval])
        script = decode_rpyc(blob, "evil.rpyc")
        self.assertEqual(script.source_format, "rpyc")
        for statement in script.statements:
            self.assertNotIsInstance(statement, type(eval))

    def test_slot_one_fallback(self) -> None:
        blob = make_rpyc({"version": 1}, [], slots=1)
        self.assertEqual(decode_rpyc(blob).statements, [])


@unittest.skipUnless(has_game1(), "test game 1 is not installed")
class Game1ScriptTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        from pgf_adapter_renpy.rpa import RpaArchive

        cls.archive = RpaArchive.open(game1_dir() / "game" / "scripts.rpa")
        cls.addClassCleanup(cls.archive.close)

    def decode(self, name: str):
        return decode_rpyc(self.archive.read(name), name)

    def test_gui_defines(self) -> None:
        script = self.decode("scripts/gui.rpyc")
        defines = script.defines()
        self.assertGreater(len(defines), 100)
        self.assertIn("gui.accent_color", defines)
        self.assertIn("#", defines["gui.accent_color"])
        self.assertIn("gui.text_font", defines)

    def test_story_labels_and_menus(self) -> None:
        script = self.decode("scripts/content/story/demo.rpyc")
        labels = script.labels()
        self.assertIn("story_7761", labels)
        self.assertTrue(any(name.startswith("choice_") for name in labels))
        menus = [s for s in script.statements for s in s.walk() if s.kind == Stmt.MENU]
        self.assertTrue(menus)
        first = menus[0]
        self.assertGreaterEqual(len(first.items), 2)
        self.assertTrue(first.items[0].text)
        self.assertTrue(first.meta.get("caption"))

    def test_nested_labels_are_found(self) -> None:
        script = self.decode("scripts/content/story/part1.rpyc")
        labels = script.labels()
        self.assertIn("choice_7_a_route_shiyu", labels)
        self.assertIn("branch_a_rooftop_common", labels)

    def test_quick_menu_screen_positions(self) -> None:
        script = self.decode("scripts/screens/screen_quick_menu.rpyc")
        screens = script.screens()
        self.assertIn("quick_menu", screens)
        screen = screens["quick_menu"]
        buttons = [e for e in screen.elements if e.kind == "imagebutton"]
        self.assertEqual(len(buttons), 7)
        self.assertTrue(all("xpos" in b.properties for b in buttons))
        self.assertTrue(all("ypos" in b.properties for b in buttons))

    def test_say_screen_uses_quick_menu(self) -> None:
        script = self.decode("scripts/screens/screen_say.rpyc")
        screens = script.screens()
        self.assertIn("say", screens)
        self.assertTrue(screens["say"].uses("quick_menu"))


@unittest.skipUnless(has_game2(), "test game 2 is not installed")
class Game2ScriptTests(unittest.TestCase):
    def test_story_menus(self) -> None:
        from pgf_adapter_renpy.rpa import RpaArchive

        with RpaArchive.open(game2_dir() / "game" / "scripts.rpa") as archive:
            script = decode_rpyc(archive.read("scripts/content/part4.rpyc"), "part4.rpyc")
        labels = script.labels()
        self.assertIn("part4", labels)
        self.assertIn("part4_good_ending", labels)
        menus = [s for s in script.statements for s in s.walk() if s.kind == Stmt.MENU]
        self.assertTrue(menus)


if __name__ == "__main__":
    unittest.main()
