from __future__ import annotations

import ast
import re
import unittest

from pgf_adapter_renpy.analyze import build_graph
from pgf_adapter_renpy.rpy_text import parse_script
from pgf_adapter_renpy.screen_emit import emit_flowchart_screen
from pgf_core.layout import compute_layout
from pgf_core.model import NodeKind
from pgf_style import preset_tokens

SOURCE = '''\
label start:
    "第一句"
    "第二句"
    menu:
        "我觉得"
        "时语":
            jump a
        "另一个":
            jump b
label a:
    "A"
    "A2"
    return
label b:
    "B"
    return
'''


class HistoryMetadataTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.result = build_graph([parse_script(SOURCE, "history.rpy")])
        cls.graph = cls.result.graph

    def test_choice_history(self) -> None:
        choice = next(n for n in self.graph.nodes.values() if n.kind is NodeKind.CHOICE)
        self.assertEqual(choice.meta["history_text"], "我觉得")
        self.assertEqual(choice.meta["history_fallback"], "第二句")

    def test_scene_history_sequence(self) -> None:
        scene = self.graph.nodes["a"]
        self.assertEqual(scene.meta["history_text"], "A")
        self.assertEqual(scene.meta["history_text2"], "A2")

    def test_ending_history(self) -> None:
        ending = next(
            n for n in self.graph.nodes.values()
            if n.kind is NodeKind.ENDING and n.meta["label"] == "a"
        )
        self.assertEqual(ending.meta["history_text"], "A2")


class HistoryEmitTests(unittest.TestCase):
    def test_rows_carry_history_text(self) -> None:
        result = build_graph([parse_script(SOURCE, "history.rpy")])
        emitted = emit_flowchart_screen(
            result.graph,
            compute_layout(result.graph),
            preset_tokens(),
        )
        match = re.search(
            r"PGF_NODES = (\[.*?\])\n    PGF_PREDECESSORS",
            emitted.content,
            re.S,
        )
        assert match is not None
        rows = {row[0]: row for row in ast.literal_eval(match.group(1))}
        self.assertTrue(all(len(row) == 12 for row in rows.values()))
        self.assertEqual(rows["a"][4], "A")
        self.assertEqual(rows["a"][5], "A2")
        choice = next(
            row for row in rows.values()
            if row[1] == "choice"
        )
        self.assertEqual(choice[4], "我觉得")
        self.assertEqual(choice[6], "第二句")
        self.assertIn("pgf_history_ids", emitted.content)
        self.assertIn("RollbackToIdentifier", emitted.content)
        self.assertNotIn("jump_out_of_context", emitted.content)


if __name__ == "__main__":
    unittest.main()
