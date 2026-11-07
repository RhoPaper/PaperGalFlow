from __future__ import annotations

import unittest

from pgf_adapter_renpy.rpy_text import parse_script
from pgf_adapter_renpy.script_model import ScriptFile
from pgf_adapter_renpy.screen_emit import FlowchartEmitOptions, emit_flowchart_screen
from pgf_adapter_renpy.analyze import build_graph
from pgf_core.layout import compute_layout
from pgf_style import preset_tokens


def sample_graph():
    from pgf_core.model import EdgeKind, FlowGraph, FlowNode, NodeKind

    graph = FlowGraph(entry="start")
    graph.add_node(FlowNode("start", NodeKind.ENTRY, title="序章", meta={"label": "start"}))
    graph.add_node(
        FlowNode(
            "menu",
            NodeKind.CHOICE,
            title="要怎么做？",
            meta={"label": "start"},
        )
    )
    graph.add_node(FlowNode("a", NodeKind.SCENE, title="向左走", meta={"label": "a"}))
    graph.add_node(FlowNode("b", NodeKind.SCENE, title="向右走", meta={"label": "b"}))
    graph.add_node(FlowNode("end_a", NodeKind.ENDING, title="结局 A", meta={"label": "a"}))
    graph.add_node(FlowNode("end_b", NodeKind.ENDING, title="结局 B", meta={"label": "b"}))
    graph.connect("start", "menu")
    graph.connect("menu", "a", EdgeKind.CHOICE, label="向左")
    graph.connect("menu", "b", EdgeKind.CHOICE, label="向右")
    graph.connect("start", "end_a", EdgeKind.CONDITION, label="hidden_condition")
    graph.connect("a", "end_a", EdgeKind.END)
    graph.connect("b", "end_b", EdgeKind.END)
    return graph


class EmitTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.graph = sample_graph()
        cls.layout = compute_layout(cls.graph)
        cls.tokens = preset_tokens()
        cls.file = emit_flowchart_screen(
            cls.graph,
            cls.layout,
            cls.tokens,
            FlowchartEmitOptions(game_name="测试游戏", entry_label="start", screen_size=(1280, 720)),
        )

    def test_header_and_name(self) -> None:
        self.assertEqual(self.file.name, "pgf_flowchart_screen.rpy")
        self.assertIn("PaperGalFlow", self.file.content.splitlines()[0])
        self.assertIn("screen pgf_flowchart", self.file.content)

    def test_generated_source_parses(self) -> None:
        script = parse_script(self.file.content, self.file.name)
        self.assertIn("pgf_flowchart", script.screens())
        self.assertNotIn("pgf_hotkey", self.file.content)  # the hook file owns that

    def test_condition_labels_hidden_by_default(self) -> None:
        self.assertNotIn("hidden_condition", self.file.content)

    def test_condition_labels_can_be_enabled(self) -> None:
        emitted = emit_flowchart_screen(
            self.graph,
            self.layout,
            self.tokens,
            FlowchartEmitOptions(show_condition_labels=True),
        )
        self.assertIn("hidden_condition", emitted.content)

    def test_runtime_data_present(self) -> None:
        for needle in (
            "PGF_NODES =",
            "PGF_PREDECESSORS =",
            "PGF_EDGE_SEGMENTS =",
            "PGF_STYLE =",
            "PGF_UI =",
            "renpy.seen_label",
            "def pgf_read_states",
            "def pgf_history_ids",
            "_history_list",
            "RollbackToIdentifier",
            "get_identifier_checkpoints",
        ):
            self.assertIn(needle, self.file.content)
        self.assertNotIn("PGFKernel", self.file.content)
        self.assertNotIn("persistent", self.file.content)
        self.assertNotIn("config.label_callbacks", self.file.content)
        self.assertNotIn("jump_out_of_context", self.file.content)

    def test_nine_patch_assets_are_used(self) -> None:
        for needle in (
            'PGF_UI["panel_top"]',
            'PGF_UI["panel_bottom"]',
            'PGF_UI["label"]',
            'PGF_UI["button"]',
            'PGF_UI["shadow"]',
            'PGF_UI["node_"',
            'Frame(PGF_UI["shadow"]',
            'Frame(PGF_UI["node_',
        ):
            self.assertIn(needle, self.file.content)
        self.assertNotIn('add Solid(_pgf_pal["border"])', self.file.content)
        self.assertNotIn('add Solid(_pgf_pal["strip"])', self.file.content)

    def test_deterministic(self) -> None:
        options = FlowchartEmitOptions(game_name="测试游戏", entry_label="start", screen_size=(1280, 720))
        other = emit_flowchart_screen(self.graph, self.layout, self.tokens, options)
        self.assertEqual(other.content, self.file.content)

    def test_history_fields_and_seen_keys(self) -> None:
        import ast
        import re

        match = re.search(
            r"PGF_NODES = (\[.*?\])\n    PGF_PREDECESSORS",
            self.file.content,
            re.S,
        )
        assert match is not None
        rows = {row[0]: row for row in ast.literal_eval(match.group(1))}
        self.assertTrue(all(len(row) == 12 for row in rows.values()))
        self.assertEqual(rows["start"][7], "start")
        self.assertEqual(rows["menu"][7], "start")
        self.assertEqual(rows["end_a"][7], "a")
        self.assertNotIn("pgf_replay", self.file.content)

    def test_no_unsafe_characters_in_screen_names(self) -> None:
        self.assertIn('screen pgf_flowchart():', self.file.content)
        self.assertIn('key "game_menu" action Return()', self.file.content)


class AnalyzeToEmitTests(unittest.TestCase):
    def test_end_to_end_graph_emit(self) -> None:
        source = '''\
label start:
    "开场"
    menu:
        "A":
            jump route_a
        "B":
            jump route_b
label route_a:
    "A 线"
    return
label route_b:
    "B 线"
    return
'''
        result = build_graph([parse_script(source, "story.rpy")])
        layout = compute_layout(result.graph)
        emitted = emit_flowchart_screen(result.graph, layout, preset_tokens())
        self.assertGreaterEqual(result.graph.stats()["nodes"], 5)
        self.assertIn("PGF_CANVAS", emitted.content)
        self.assertNotIn("None", emitted.content.split("PGF_NODES =")[1].split("PGF_EDGE_SEGMENTS")[0])


if __name__ == "__main__":
    unittest.main()
