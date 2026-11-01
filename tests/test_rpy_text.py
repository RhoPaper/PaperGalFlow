from __future__ import annotations

import unittest

from pgf_adapter_renpy.rpy_text import parse_script
from pgf_adapter_renpy.script_model import Stmt

SAMPLE = '''\
# leading comment
define gui.accent_color = "#0099ff"
define e = Character("Eileen")
default persistent.foo = True

label start:
    "旁白里可以有 # 号"
    e "你好，世界。"
    menu:
        "选一个吧"
        "去左边":
            $ left = True
            jump left_branch
        "去右边" if right_available:
            jump .right
    "两个选项汇合了"

    label .right:
        "这是本地标签"
        return

label left_branch:
    scene bg room
    with dissolve
    play music "bgm.ogg" fadein 1.0
    if flag and other:
        jump start
    elif second:
        call helper from _call_helper
    else:
        return

label helper:
    """
    多行
    旁白
    """
    return

screen quick_menu():
    zorder 100
    imagebutton:
        xpos 1351
        ypos 1354
        action ShowMenu("save")

screen say(who, what):
    use quick_menu

style pgf_node:
    background "#101010"
    padding (4, 4)

translate japanese start:
    e "こんにちは"

label tail:
    "结束"
    return
'''


class TextParserTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.script = parse_script(SAMPLE, "sample.rpy")
        cls.labels = cls.script.labels()

    def test_format(self) -> None:
        self.assertEqual(self.script.source_format, "rpy")
        self.assertIn("label start", self.script.source_text)

    def test_labels(self) -> None:
        self.assertEqual(
            set(self.labels),
            {"start", "start.right", "left_branch", "helper", "tail"},
        )

    def test_defines_and_defaults(self) -> None:
        defines = self.script.defines()
        self.assertEqual(defines["gui.accent_color"], '"#0099ff"')
        self.assertEqual(defines["e"], 'Character("Eileen")')
        self.assertEqual(defines["persistent.foo"], "True")

    def test_dialogue_is_not_tricked_by_comments_or_keywords(self) -> None:
        start = self.labels["start"]
        say_texts = [n.text for n in start.walk() if n.kind == Stmt.SAY]
        self.assertIn("旁白里可以有 # 号", say_texts)
        self.assertIn("你好，世界。", say_texts)
        self.assertNotIn("bgm.ogg", " ".join(say_texts))
        left = self.labels["left_branch"]
        self.assertFalse(any(s.kind == Stmt.SAY for s in left.block))

    def test_menu_items_and_conditions(self) -> None:
        start = self.labels["start"]
        menu = next(s for s in start.walk() if s.kind == Stmt.MENU)
        self.assertEqual(menu.meta["caption"], "选一个吧")
        self.assertEqual([item.text for item in menu.items], ["去左边", "去右边"])
        self.assertEqual(menu.items[1].condition, "right_available")
        self.assertEqual(menu.items[0].block[1].target, "left_branch")

    def test_local_label_and_jump_resolution(self) -> None:
        start = self.labels["start"]
        menu = next(s for s in start.walk() if s.kind == Stmt.MENU)
        self.assertEqual(menu.items[1].block[0].target, "start.right")
        self.assertIn("start.right", self.labels)

    def test_if_elif_else(self) -> None:
        left = self.labels["left_branch"]
        branch = next(s for s in left.walk() if s.kind == Stmt.IF)
        self.assertEqual(len(branch.entries), 3)
        self.assertEqual(branch.entries[0].condition, "flag and other")
        self.assertEqual(branch.entries[1].condition, "second")
        self.assertEqual(branch.entries[2].condition, "True")
        self.assertEqual(branch.entries[1].block[0].kind, Stmt.CALL)
        self.assertEqual(branch.entries[1].block[0].target, "helper")

    def test_triple_quoted_say(self) -> None:
        helper = self.labels["helper"]
        says = [n.text for n in helper.walk() if n.kind == Stmt.SAY]
        self.assertEqual(len(says), 1)
        self.assertIn("多行", says[0])
        self.assertIn("旁白", says[0])

    def test_screens(self) -> None:
        screens = self.script.screens()
        self.assertIn("quick_menu", screens)
        quick = screens["quick_menu"]
        self.assertEqual(quick.properties.get("zorder"), "100")
        button = next(e for e in quick.elements if e.kind == "imagebutton")
        self.assertEqual(button.properties["xpos"], "1351")
        self.assertIn("say", screens)
        self.assertTrue(screens["say"].uses("quick_menu"))

    def test_styles(self) -> None:
        styles = self.script.styles()
        self.assertIn("pgf_node", styles)
        self.assertEqual(styles["pgf_node"]["background"], '"#101010"')
        self.assertEqual(styles["pgf_node"]["padding"], "(4, 4)")

    def test_translations_are_skipped(self) -> None:
        self.assertEqual(len(self.labels), 5)
        self.assertNotIn("translate", self.labels)

    def test_start_is_entry_candidate(self) -> None:
        self.assertIn("start", self.labels)


class EdgeCaseTests(unittest.TestCase):
    def test_empty_file(self) -> None:
        script = parse_script("", "empty.rpy")
        self.assertEqual(script.statements, [])

    def test_unknown_statements_do_not_raise(self) -> None:
        script = parse_script(
            'label a:\n    weird_statement "x" with stuff\n    return\n', "weird.rpy"
        )
        self.assertIn("a", script.labels())

    def test_menu_without_items(self) -> None:
        script = parse_script("label a:\n    menu:\n    return\n", "menu.rpy")
        menu = next(s for s in script.statements[0].walk() if s.kind == Stmt.MENU)
        self.assertEqual(menu.items, [])

    def test_python_blocks_are_captured(self) -> None:
        script = parse_script(
            'init python:\n    def helper():\n        return 1\n\npython hide:\n    x = 2\n',
            "python.rpy",
        )
        sources = [s.source for s in script.statements if s.kind == Stmt.PYTHON]
        self.assertTrue(any("def helper" in source for source in sources))
        self.assertTrue(any("x = 2" in source for source in sources))

    def test_quoted_hash_is_kept(self) -> None:
        script = parse_script('label a:\n    "a # b"\n    return\n', "hash.rpy")
        says = [s.text for s in script.statements[0].walk() if s.kind == Stmt.SAY]
        self.assertEqual(says, ["a # b"])


if __name__ == "__main__":
    unittest.main()
