from __future__ import annotations

import unittest

from pgf_core.model import EdgeKind, FlowGraph, FlowNode, NodeKind
from pgf_core.errors import GraphError


def diamond() -> FlowGraph:
    graph = FlowGraph()
    graph.add_node(FlowNode("entry", NodeKind.ENTRY, title="序章"))
    graph.add_node(FlowNode("a", NodeKind.CHOICE, title="要不要去？"))
    graph.add_node(FlowNode("left", NodeKind.SCENE, title="向左"))
    graph.add_node(FlowNode("right", NodeKind.SCENE, title="向右"))
    graph.add_node(FlowNode("end", NodeKind.ENDING, title="结局"))
    graph.connect("entry", "a")
    graph.connect("a", "left", EdgeKind.CHOICE, label="向左")
    graph.connect("a", "right", EdgeKind.CHOICE, label="向右")
    graph.connect("left", "end")
    graph.connect("right", "end")
    return graph


class FlowGraphTests(unittest.TestCase):
    def test_entry_is_auto_detected(self) -> None:
        graph = FlowGraph()
        graph.add_node(FlowNode("start", NodeKind.ENTRY))
        self.assertEqual(graph.entry, "start")

    def test_duplicate_node_rejected(self) -> None:
        graph = FlowGraph()
        graph.add_node(FlowNode("a"))
        with self.assertRaises(GraphError):
            graph.add_node(FlowNode("a"))

    def test_ensure_node_fills_missing_data(self) -> None:
        graph = FlowGraph()
        node = graph.ensure_node("a", NodeKind.CHOICE)
        self.assertEqual(node.title, "")
        graph.ensure_node("a", title="选择", subtitle="副标题")
        self.assertEqual(graph.nodes["a"].title, "选择")
        self.assertEqual(graph.nodes["a"].subtitle, "副标题")

    def test_edges_are_deduplicated(self) -> None:
        graph = diamond()
        before = len(graph.edges)
        self.assertFalse(graph.connect("entry", "a"))
        self.assertEqual(len(graph.edges), before)

    def test_self_loop_is_ignored(self) -> None:
        graph = diamond()
        before = len(graph.edges)
        self.assertFalse(graph.connect("left", "left"))
        self.assertEqual(len(graph.edges), before)

    def test_unknown_endpoint_raises(self) -> None:
        graph = diamond()
        with self.assertRaises(GraphError):
            graph.connect("entry", "missing")

    def test_reachability_and_pruning(self) -> None:
        graph = diamond()
        graph.add_node(FlowNode("orphan", NodeKind.SCENE))
        self.assertEqual(graph.reachable(), {"entry", "a", "left", "right", "end"})
        removed = graph.prune_unreachable()
        self.assertEqual(removed, ("orphan",))
        self.assertNotIn("orphan", graph.nodes)

    def test_call_edges_are_optional_for_reachability(self) -> None:
        graph = diamond()
        graph.add_node(FlowNode("utility", NodeKind.SCENE))
        graph.connect("left", "utility", EdgeKind.CALL)
        self.assertIn("utility", graph.reachable(include_calls=True))
        self.assertNotIn("utility", graph.reachable(include_calls=False))

    def test_validate_detects_missing_entry(self) -> None:
        graph = diamond()
        graph.remove_node("entry")
        with self.assertRaises(GraphError):
            graph.validate()

    def test_roundtrip_serialisation(self) -> None:
        graph = diamond()
        restored = FlowGraph.from_dict(graph.to_dict())
        self.assertEqual(restored.to_dict(), graph.to_dict())
        self.assertEqual(restored.stats(), graph.stats())

    def test_stats(self) -> None:
        stats = diamond().stats()
        self.assertEqual(stats["nodes"], 5)
        self.assertEqual(stats["node_kinds"]["choice"], 1)
        self.assertEqual(stats["endings"], 1)
        self.assertEqual(stats["edge_kinds"]["choice"], 2)

    def test_subgraph_picks_fallback_entry(self) -> None:
        graph = diamond()
        sub = graph.subgraph({"a", "left", "right"})
        self.assertEqual(sub.entry, "a")
        self.assertEqual(len(sub.edges), 2)

    def test_title_for_locked_node(self) -> None:
        node = FlowNode("a", title="秘密")
        self.assertEqual(node.title_for("locked"), "？？？")
        self.assertEqual(node.title_for("read"), "秘密")


if __name__ == "__main__":
    unittest.main()
