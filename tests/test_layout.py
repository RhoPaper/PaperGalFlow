from __future__ import annotations

import unittest

from pgf_core.layout import LayoutConfig, compute_layout
from pgf_core.model import EdgeKind, FlowGraph, FlowNode, NodeKind


def linear_graph() -> FlowGraph:
    graph = FlowGraph(entry="a")
    graph.add_node(FlowNode("a", NodeKind.ENTRY, title="A"))
    graph.add_node(FlowNode("b", NodeKind.SCENE, title="B"))
    graph.add_node(FlowNode("c", NodeKind.ENDING, title="C"))
    graph.connect("a", "b")
    graph.connect("b", "c")
    return graph


def diamond_graph() -> FlowGraph:
    graph = FlowGraph(entry="a")
    graph.add_node(FlowNode("a", NodeKind.ENTRY, title="A"))
    graph.add_node(FlowNode("b", NodeKind.CHOICE, title="B"))
    graph.add_node(FlowNode("c", NodeKind.SCENE, title="C"))
    graph.add_node(FlowNode("d", NodeKind.SCENE, title="D"))
    graph.add_node(FlowNode("e", NodeKind.ENDING, title="E"))
    graph.connect("a", "b")
    graph.connect("b", "c", EdgeKind.CHOICE, label="C")
    graph.connect("b", "d", EdgeKind.CHOICE, label="D")
    graph.connect("c", "e")
    graph.connect("d", "e")
    return graph


class LayoutTests(unittest.TestCase):
    def test_empty_graph(self) -> None:
        layout = compute_layout(FlowGraph())
        self.assertEqual(layout.width, 0)
        self.assertEqual(layout.positions, {})

    def test_linear_layers(self) -> None:
        layout = compute_layout(linear_graph())
        self.assertEqual(layout.layer_of["a"], 0)
        self.assertEqual(layout.layer_of["b"], 1)
        self.assertEqual(layout.layer_of["c"], 2)
        self.assertLess(layout.positions["a"].y, layout.positions["b"].y)
        self.assertLess(layout.positions["b"].y, layout.positions["c"].y)

    def test_edges_are_orthogonal(self) -> None:
        layout = compute_layout(diamond_graph())
        for edge in layout.edges:
            for first, second in zip(edge.points, edge.points[1:]):
                self.assertTrue(
                    first.x == second.x or first.y == second.y,
                    f"non orthogonal segment {first}->{second} on {edge.source}->{edge.target}",
                )

    def test_edges_start_and_end_on_node_borders(self) -> None:
        graph = diamond_graph()
        layout = compute_layout(graph)
        for edge in layout.edges:
            if edge.back:
                continue
            source = layout.positions[edge.source]
            target = layout.positions[edge.target]
            self.assertEqual(edge.points[0].y, source.bottom)
            self.assertEqual(edge.points[-1].y, target.y)

    def test_nodes_do_not_overlap(self) -> None:
        layout = compute_layout(diamond_graph())
        rects = list(layout.positions.values())
        for i, left in enumerate(rects):
            for right in rects[i + 1 :]:
                overlap = not (
                    left.right <= right.x
                    or right.right <= left.x
                    or left.bottom <= right.y
                    or right.bottom <= left.y
                )
                self.assertFalse(overlap, f"{left} overlaps {right}")

    def test_long_edge_gets_virtual_slot(self) -> None:
        graph = FlowGraph(entry="a")
        for node_id in "abc":
            graph.add_node(FlowNode(node_id, NodeKind.SCENE))
        graph.connect("a", "b")
        graph.connect("b", "c")
        graph.connect("a", "c")
        layout = compute_layout(graph)
        long_edge = next(e for e in layout.edges if e.source == "a" and e.target == "c")
        self.assertGreaterEqual(len(long_edge.points), 4)
        # The long edge must not cross the middle node b.
        b = layout.positions["b"]
        for first, second in zip(long_edge.points, long_edge.points[1:]):
            if first.y == second.y and first.x != second.x:
                y = first.y
                if b.y < y < b.bottom:
                    left, right = sorted((first.x, second.x))
                    self.assertFalse(left < b.center_x < right)

    def test_cycle_is_routed_back(self) -> None:
        graph = FlowGraph(entry="a")
        for node_id in "abc":
            graph.add_node(FlowNode(node_id, NodeKind.SCENE))
        graph.connect("a", "b")
        graph.connect("b", "c")
        graph.connect("c", "a")
        layout = compute_layout(graph)
        back = [e for e in layout.edges if e.back]
        self.assertEqual(len(back), 1)
        self.assertEqual((back[0].source, back[0].target), ("c", "a"))
        self.assertGreater(max(p.x for p in back[0].points), max(r.right for r in layout.positions.values()) - 1)

    def test_call_edge_uses_side_channel(self) -> None:
        graph = diamond_graph()
        graph.add_node(FlowNode("util", NodeKind.SCENE))
        graph.connect("b", "util", EdgeKind.CALL)
        layout = compute_layout(graph)
        call = next(e for e in layout.edges if e.kind is EdgeKind.CALL)
        self.assertTrue(call.back)
        self.assertGreater(call.points[0].x, layout.positions["b"].right - 1)

    def test_layout_is_deterministic(self) -> None:
        graph = diamond_graph()
        first = compute_layout(graph)
        second = compute_layout(graph)
        self.assertEqual(first.positions, second.positions)
        self.assertEqual([e.points for e in first.edges], [e.points for e in second.edges])

    def test_wide_graph_has_positive_size(self) -> None:
        graph = diamond_graph()
        layout = compute_layout(graph)
        self.assertGreater(layout.width, 0)
        self.assertGreater(layout.height, 0)
        self.assertGreater(layout.width, layout.positions["a"].right)

    def test_custom_config(self) -> None:
        config = LayoutConfig(node_width=100, node_height=40, h_gap=10, v_gap=10)
        layout = compute_layout(diamond_graph(), config)
        self.assertEqual(layout.positions["a"].w, 100)
        self.assertEqual(layout.positions["a"].h, 40)

    def test_scaled_copy(self) -> None:
        layout = compute_layout(linear_graph())
        scaled = layout.scaled(0.5)
        self.assertEqual(scaled.positions["a"].w, layout.positions["a"].w // 2)
        self.assertEqual(scaled.width, int(round(layout.width * 0.5)))


if __name__ == "__main__":
    unittest.main()
