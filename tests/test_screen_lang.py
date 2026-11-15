from __future__ import annotations

import unittest
from pathlib import Path

from pgf_adapter_renpy.entry import EntryOptions, build_entry_plan
from pgf_adapter_renpy.installer import static_check
from pgf_adapter_renpy.rpy_text import parse_script
from pgf_adapter_renpy.screen_lang import decompile_screen, render_screen
from pgf_adapter_renpy.script_model import ScreenElement, ScreenInfo
from pgf_adapter_renpy.style_probe import QuickButton, QuickMenuProbe
from pgf_style import preset_tokens

from .game_paths import game1_dir, game2_dir, has_game1, has_game2


def sample_screen() -> ScreenInfo:
    return ScreenInfo(
        name="quick_menu",
        properties={"zorder": "10", "style_prefix": '"quick"'},
        elements=[
            ScreenElement(
                kind="vbox",
                properties={"xalign": "1.0", "yalign": "1.0"},
                children=[
                    ScreenElement(
                        kind="imagebutton",
                        properties={
                            "idle": '"gui/q.png"',
                            "hover": '"gui/q_hover.png"',
                            "action": 'ShowMenu("save")',
                        },
                    ),
                    ScreenElement(
                        kind="textbutton",
                        positionals=['"存档"'],
                        properties={"action": 'ShowMenu("save")'},
                    ),
                    ScreenElement(kind="text", text='"标题"', properties={"size": "20"}),
                ],
            ),
            ScreenElement(
                kind="if",
                branches=[
                    (
                        "config.developer",
                        [ScreenElement(kind="text", text='"debug"')],
                    ),
                    ("", [ScreenElement(kind="null")]),
                ],
            ),
            ScreenElement(
                kind="for",
                for_variable="item",
                for_expression="items",
                children=[ScreenElement(kind="text", text="item")],
            ),
            ScreenElement(kind="use", target="say"),
        ],
    )


class DecompilerTests(unittest.TestCase):
    def test_nested_screen_is_rendered(self) -> None:
        result = decompile_screen(sample_screen())
        self.assertTrue(result.supported, result.warnings)
        source = result.source
        self.assertIn("vbox:", source)
        self.assertIn("imagebutton:", source)
        self.assertIn('textbutton "存档":', source)
        self.assertIn('if config.developer:', source)
        self.assertIn("else:", source)
        self.assertIn("for item in items:", source)
        self.assertIn("use say", source)
        self.assertIn("    zorder 10", source)
        self.assertIn('    style_prefix "quick"', source)

    def test_full_screen_parses(self) -> None:
        result = render_screen(sample_screen())
        self.assertTrue(result.supported, result.warnings)
        script = parse_script(result.source, "decompiled.rpy")
        self.assertIn("quick_menu", script.screens())

    def test_unsupported_atl_rejected(self) -> None:
        screen = ScreenInfo(
            name="quick_menu",
            elements=[ScreenElement(kind="atl", children=[ScreenElement(kind="text")])],
        )
        result = decompile_screen(screen)
        self.assertFalse(result.supported)
        self.assertTrue(result.warnings)

    def test_invalid_property_rejected(self) -> None:
        screen = ScreenInfo(
            name="quick_menu",
            elements=[
                ScreenElement(kind="text", text='"x"', properties={"bad key": "1"})
            ],
        )
        self.assertFalse(decompile_screen(screen).supported)

    def test_decompiled_entry_plan(self) -> None:
        probe = QuickMenuProbe(
            screen_name="quick_menu",
            found=True,
            has_source=False,
            source=decompile_screen(sample_screen()).source,
            decompiled=True,
            source_format="rpyc-decompiled",
            properties={"zorder": "10"},
            parameters="()",
            buttons=[QuickButton(100, 300, 120, 50, "gui/q.png")],
            screen_size=(1280, 720),
        )
        plan = build_entry_plan(preset_tokens(), probe, EntryOptions(screen_size=(1280, 720)))
        self.assertEqual(plan.mode, "quick_menu_patch")
        self.assertIn("reconstructed from compiled SL2", plan.reason)
        self.assertIn("screen quick_menu():", plan.file.content)
        self.assertIn("zorder 10", plan.file.content)
        self.assertEqual(static_check([plan.file]), [])


@unittest.skipUnless(has_game1(), "test game 1 is not installed")
class RealGame1DecompileTests(unittest.TestCase):
    def test_quick_menu(self) -> None:
        from pgf_adapter_renpy.archive import GameArchive

        with GameArchive.open(game1_dir() / "game") as archive:
            screens = {}
            for script in archive.parse_all().values():
                screens.update(script.screens())
        result = decompile_screen(screens["quick_menu"])
        self.assertTrue(result.supported, result.warnings)
        self.assertIn("imagebutton:", result.source)
        self.assertEqual(result.element_count, 7)
        script = parse_script(result.screen_source(), "decompiled.rpy")
        self.assertIn("quick_menu", script.screens())


@unittest.skipUnless(has_game2(), "test game 2 is not installed")
class RealGame2DecompileTests(unittest.TestCase):
    def test_quick_menu_if_branch(self) -> None:
        from pgf_adapter_renpy.archive import GameArchive

        with GameArchive.open(game2_dir() / "game") as archive:
            screens = {}
            for script in archive.parse_all().values():
                screens.update(script.screens())
        result = decompile_screen(screens["quick_menu"])
        self.assertTrue(result.supported, result.warnings)
        self.assertIn("if _get_voice_info().filename is not None:", result.source)
        self.assertIn("dialog_menu_revoice_normal.png", result.source)


if __name__ == "__main__":
    unittest.main()
