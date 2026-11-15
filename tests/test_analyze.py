from __future__ import annotations

import unittest

from pgf_adapter_renpy.analyze import AnalyzeOptions, build_graph, clean_text
from pgf_adapter_renpy.rpy_text import parse_script
from pgf_adapter_renpy.script_model import ScriptFile
from pgf_core.model import EdgeKind, NodeKind

from .game_paths import game1_dir, game2_dir, has_game1, has_game2

FIXTURE = '''\
label start:
    jump chapter1

label chapter1:
    "第一章"
    menu:
        "A":
            jump branch_a
        "B":
            jump branch_b
        "C":
            jump fall_a

label branch_a:
    "A 线"
    if flag:
        jump good
    else:
        jump bad

label branch_b:
    "B 线"
    call helper
    return

label good:
    "好结局"
    return

label bad:
    "坏结局"
    return

label helper:
    "辅助剧情"
    return

label unreachable:
    "不该出现"
    jump start

label fall_a:
    "会掉下去的剧情"
label fall_b:
    "掉到这里"
    jump splashscreen
'''


def build(script: str, **options: object):
    parsed = parse_script(script, "fixture.rpy")
    return build_graph([parsed], AnalyzeOptions(**options))  # type: ignore[arg-type]


class SyntheticAnalyzeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.result = build(FIXTURE)
        cls.graph = cls.result.graph

    def test_entry_router_is_collapsed(self) -> None:
        self.assertNotIn("start", self.graph.nodes)
        self.assertIn("chapter1", self.graph.nodes)
        self.assertEqual(self.result.entry_label, "start")
        self.assertEqual(self.graph.entry, "chapter1")
        self.assertIs(self.graph.nodes["chapter1"].kind, NodeKind.ENTRY)

    def test_choice_node_and_edges(self) -> None:
        choices = [n for n in self.graph.nodes.values() if n.kind is NodeKind.CHOICE]
        self.assertEqual(len(choices), 1)
        menu = choices[0]
        outgoing = self.graph.outgoing(menu.id)
        self.assertEqual({e.target for e in outgoing}, {"branch_a", "branch_b", "fall_a"})
        self.assertEqual({e.label for e in outgoing}, {"A", "B", "C"})
        self.assertTrue(all(e.kind is EdgeKind.CHOICE for e in outgoing))

    def test_condition_node(self) -> None:
        conditions = [n for n in self.graph.nodes.values() if n.kind is NodeKind.CONDITION]
        self.assertEqual(len(conditions), 1)
        outgoing = self.graph.outgoing(conditions[0].id)
        self.assertEqual({e.target for e in outgoing}, {"good", "bad"})
        self.assertTrue(all(e.kind is EdgeKind.CONDITION for e in outgoing))

    def test_endings(self) -> None:
        endings = self.graph.endings()
        self.assertEqual(len(endings), 4)
        for ending in endings:
            self.assertTrue(self.graph.incoming(ending))

    def test_unreachable_labels_are_pruned(self) -> None:
        self.assertNotIn("unreachable", self.graph.nodes)
        self.assertNotIn("helper", self.graph.nodes)

    def test_call_edges_are_dropped_with_side_labels(self) -> None:
        self.assertFalse(any(e.kind is EdgeKind.CALL for e in self.graph.edges))

    def test_special_ending(self) -> None:
        specials = [n for n in self.graph.nodes.values() if n.meta.get("special") == "splashscreen"]
        self.assertEqual(len(specials), 1)
        node = specials[0]
        self.assertIs(node.kind, NodeKind.ENDING)
        self.assertEqual(node.title, "返回标题画面")
        self.assertEqual(node.meta["label"], "")

    def test_fallthrough_links_next_label(self) -> None:
        self.assertIn("fall_a", self.graph.nodes)
        self.assertIn("fall_b", self.graph.nodes)
        targets = {edge.target for edge in self.graph.outgoing("fall_a")}
        self.assertEqual(targets, {"fall_b"})
        self.assertTrue(any("falls through" in note for note in self.result.notes))

    def test_no_warnings(self) -> None:
        self.assertEqual(self.result.warnings, [])

    def test_graph_is_valid(self) -> None:
        self.graph.validate()
        self.assertTrue(self.graph.reachable())
        self.assertEqual(self.graph.stats()["nodes"], len(self.graph.nodes))

    def test_deterministic(self) -> None:
        again = build(FIXTURE)
        self.assertEqual(again.graph.to_dict(), self.graph.to_dict())

    def test_include_side_labels(self) -> None:
        result = build(FIXTURE, include_side_labels=True)
        self.assertIn("helper", result.graph.nodes)
        self.assertTrue(any(e.kind is EdgeKind.CALL for e in result.graph.edges))

    def test_call_edges_can_be_disabled(self) -> None:
        result = build(FIXTURE, include_side_labels=True, include_call_edges=False)
        # Without a call edge the side label is unreachable, so it is pruned.
        self.assertNotIn("helper", result.graph.nodes)
        self.assertFalse(any(e.kind is EdgeKind.CALL for e in result.graph.edges))

    def test_custom_entry(self) -> None:
        result = build(FIXTURE, entry_label="branch_b")
        self.assertEqual(result.graph.entry, "branch_b")


class CleanTextTests(unittest.TestCase):
    def test_tags_and_newlines(self) -> None:
        self.assertEqual(clean_text("{b}你好{/b}\n世界", 10), "你好 世界")

    def test_truncation(self) -> None:
        result = clean_text("一二三四五六七八九十", 6)
        self.assertTrue(result.endswith("…"))
        self.assertLessEqual(len(result), 6)

    def test_quotes_are_stripped(self) -> None:
        self.assertEqual(clean_text('"引用"', 10), "引用")


@unittest.skipUnless(has_game1(), "test game 1 is not installed")
class RealGame1Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        from pgf_adapter_renpy.archive import GameArchive

        with GameArchive.open(game1_dir() / "game") as archive:
            cls.result = build_graph(archive.parse_all().values())
        cls.graph = cls.result.graph

    def test_no_warnings_and_valid(self) -> None:
        self.assertEqual(self.result.warnings, [])
        self.graph.validate()

    def test_expected_entry(self) -> None:
        self.assertEqual(self.graph.entry, "story_7761")
        self.assertEqual(self.graph.nodes["story_7761"].kind, NodeKind.ENTRY)

    def test_expected_choices(self) -> None:
        choices = [n for n in self.graph.nodes.values() if n.kind is NodeKind.CHOICE]
        self.assertEqual(len(choices), 3)
        for node in choices:
            self.assertGreaterEqual(len(self.graph.outgoing(node.id)), 2)

    def test_multiple_endings(self) -> None:
        self.assertGreaterEqual(len(self.graph.endings()), 3)

    def test_all_nodes_reachable(self) -> None:
        reachable = self.graph.reachable(include_calls=True)
        self.assertEqual(reachable, set(self.graph.nodes))

    def test_no_internal_labels(self) -> None:
        self.assertFalse(any(node.id.startswith("_") for node in self.graph.nodes.values()))

    def test_deterministic(self) -> None:
        from pgf_adapter_renpy.archive import GameArchive

        with GameArchive.open(game1_dir() / "game") as archive:
            again = build_graph(archive.parse_all().values())
        self.assertEqual(again.graph.to_dict(), self.graph.to_dict())


@unittest.skipUnless(has_game2(), "test game 2 is not installed")
class RealGame2Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        from pgf_adapter_renpy.archive import GameArchive

        with GameArchive.open(game2_dir() / "game") as archive:
            cls.result = build_graph(archive.parse_all().values())
        cls.graph = cls.result.graph

    def test_story_is_reachable(self) -> None:
        for node_id in ("part1", "part2", "part3", "part4", "extra1"):
            self.assertIn(node_id, self.graph.nodes)

    def test_gallery_gate_is_the_entry(self) -> None:
        self.assertIn("start::if6", self.graph.nodes)
        self.assertEqual(self.graph.entry, "start::if6")

    def test_bad_ending_maps_to_title_screen(self) -> None:
        specials = [n for n in self.graph.nodes.values() if n.meta.get("special")]
        self.assertEqual(len(specials), 1)
        self.assertEqual(specials[0].title, "返回标题画面")

    def test_utility_labels_are_not_charted(self) -> None:
        for name in ("achievement", "splashscreen", "disable_user_interaction"):
            self.assertNotIn(name, self.graph.nodes)


if __name__ == "__main__":
    unittest.main()


class LoopAndDynamicTests(unittest.TestCase):
    def test_while_loop_menu_and_break(self) -> None:
        source = '''\
label start:
    "开始"
    while flag:
        menu:
            "继续":
                "再试一次"
            "离开":
                break
    "结束"
    return
'''
        result = build_graph([parse_script(source, "loop.rpy")])
        loops = [n for n in result.graph.nodes.values() if n.title == "循环"]
        self.assertEqual(len(loops), 1)
        loop_id = loops[0].id
        outgoing = result.graph.outgoing(loop_id)
        self.assertEqual({edge.kind for edge in outgoing}, {EdgeKind.CONDITION})
        self.assertTrue(any(edge.label == "循环体" for edge in outgoing))
        self.assertTrue(any(edge.label == "结束循环" for edge in outgoing))
        menu_edges = [
            edge for edge in result.graph.edges if edge.kind is EdgeKind.CHOICE
        ]
        self.assertGreaterEqual(len(menu_edges), 2)

    def test_for_loop_and_continue(self) -> None:
        source = '''\
label start:
    for item in items:
        if item:
            continue
        "x"
    "done"
    return
'''
        result = build_graph([parse_script(source, "loop.rpy")])
        self.assertTrue(any(node.title == "遍历" for node in result.graph.nodes.values()))
        self.assertTrue(any(edge.kind is EdgeKind.CONDITION for edge in result.graph.edges))

    def test_break_outside_loop_is_reported(self) -> None:
        source = '''\
label start:
    break
    "after"
    return
'''
        result = build_graph([parse_script(source, "loop.rpy")])
        self.assertTrue(any("outside a loop" in warning for warning in result.warnings))

    def test_dynamic_call_from_constant(self) -> None:
        source = '''\
define route = "branch"
label start:
    call expression route
    "after call"
    return
label branch:
    "branch"
    return
'''
        result = build_graph(
            [parse_script(source, "dynamic.rpy")], AnalyzeOptions(include_side_labels=True)
        )
        calls = [edge for edge in result.graph.edges if edge.kind is EdgeKind.CALL]
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0].target, "branch")

    def test_dynamic_jump_literal(self) -> None:
        source = '''\
label start:
    jump expression "branch"
label branch:
    "branch"
    return
'''
        result = build_graph(
            [parse_script(source, "dynamic.rpy")],
            AnalyzeOptions(collapse_routers=False),
        )
        self.assertTrue(any(edge.target == "branch" for edge in result.graph.edges))

    def test_unresolved_dynamic_call_is_noted(self) -> None:
        source = '''\
label start:
    call expression get_route()
    "after"
    return
'''
        result = build_graph([parse_script(source, "dynamic.rpy")])
        self.assertTrue(any("dynamic call not resolved" in note for note in result.notes))

    def test_translate_say_is_skipped(self) -> None:
        from pgf_adapter_renpy.script_model import ScriptFile, Statement, Stmt

        translated = Statement(
            kind=Stmt.SAY,
            line=1,
            text="translated",
            meta={"translate": "1"},
        )
        original = Statement(kind=Stmt.SAY, line=2, text="original")
        label = Statement(
            kind=Stmt.LABEL,
            line=0,
            name="start",
            block=[translated, original],
        )
        script = ScriptFile("x", statements=[label])
        result = build_graph([script])
        self.assertEqual(result.graph.nodes["start"].title, "original")


if __name__ == "__main__":
    unittest.main()
