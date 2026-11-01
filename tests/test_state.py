from __future__ import annotations

import unittest

from pgf_core.model import EdgeKind, FlowGraph, FlowNode, NodeKind
from pgf_core.state import (
    NodeState,
    ProgressState,
    PGFDictStore,
    kernel_for_graph,
    runtime_kernel_source,
)


def make_graph() -> FlowGraph:
    graph = FlowGraph(entry="start")
    graph.add_node(FlowNode("start", NodeKind.ENTRY, title="序章", meta={"label": "start"}))
    graph.add_node(FlowNode("a", NodeKind.CHOICE, title="选择", meta={"label": "a"}))
    graph.add_node(FlowNode("b", NodeKind.SCENE, title="B 线", meta={"label": "b"}))
    graph.add_node(FlowNode("c", NodeKind.SCENE, title="C 线", meta={"label": "c"}))
    graph.add_node(FlowNode("end", NodeKind.ENDING, title="结局", meta={"label": "b"}))
    graph.connect("start", "a")
    graph.connect("a", "b", EdgeKind.CHOICE, label="去 B")
    graph.connect("a", "c", EdgeKind.CHOICE, label="去 C")
    graph.connect("b", "end", EdgeKind.END)
    return graph


class RuntimeKernelTests(unittest.TestCase):
    def test_initial_states(self) -> None:
        graph = make_graph()
        kernel = kernel_for_graph(graph)
        states = kernel.states()
        self.assertEqual(states["start"], "unread")
        self.assertEqual(states["a"], "locked")
        self.assertEqual(states["b"], "locked")
        self.assertEqual(states["end"], "ending_locked")

    def test_visiting_reveals_successors(self) -> None:
        graph = make_graph()
        kernel = kernel_for_graph(graph)
        kernel.mark_seen("start")
        states = kernel.states()
        self.assertEqual(states["start"], "read")
        self.assertEqual(states["a"], "unread")
        self.assertEqual(states["b"], "locked")

    def test_label_map_marks_ending_nodes(self) -> None:
        graph = make_graph()
        kernel = kernel_for_graph(graph)
        kernel.mark_seen("b")
        states = kernel.states()
        self.assertEqual(states["b"], "read")
        self.assertEqual(states["end"], "ending_read")

    def test_states_persist_in_store(self) -> None:
        graph = make_graph()
        store = PGFDictStore()
        kernel = kernel_for_graph(graph, store)
        kernel.mark_seen("start")
        again = kernel_for_graph(graph, store)
        self.assertEqual(again.states()["start"], "read")

    def test_reset(self) -> None:
        graph = make_graph()
        store = PGFDictStore()
        kernel = kernel_for_graph(graph, store)
        kernel.mark_seen("start")
        kernel.reset()
        self.assertEqual(kernel.states()["start"], "unread")

    def test_chosen_edges(self) -> None:
        graph = make_graph()
        kernel = kernel_for_graph(graph)
        self.assertTrue(kernel.mark_chosen("a", "b"))
        self.assertFalse(kernel.mark_chosen("a", "b"))
        self.assertTrue(kernel.is_chosen("a", "b"))
        self.assertEqual(kernel.chosen(), (("a", "b"),))

    def test_call_edges_do_not_unlock_nodes(self) -> None:
        graph = make_graph()
        graph.add_node(FlowNode("utility", NodeKind.SCENE))
        graph.connect("start", "utility", EdgeKind.CALL)
        kernel = kernel_for_graph(graph)
        kernel.mark_seen("start")
        self.assertEqual(kernel.states()["utility"], "locked")

    def test_summary(self) -> None:
        graph = make_graph()
        kernel = kernel_for_graph(graph)
        kernel.mark_seen("start")
        summary = kernel.summary()
        self.assertEqual(summary["seen"], 1)
        self.assertEqual(summary["unread"], 1)
        self.assertEqual(summary["ending_total"], 1)


class ProgressStateTests(unittest.TestCase):
    def test_resolve_matches_kernel(self) -> None:
        graph = make_graph()
        progress = ProgressState()
        progress.mark_seen("start", "a", "b")
        states = progress.resolve(graph)
        self.assertEqual(states["start"], NodeState.READ)
        self.assertEqual(states["c"], NodeState.UNREAD)
        self.assertEqual(states["end"], NodeState.ENDING_LOCKED)

    def test_summary_counts(self) -> None:
        graph = make_graph()
        progress = ProgressState()
        progress.mark_seen("start")
        summary = progress.summary(graph)
        self.assertEqual(summary["total"], 5)
        self.assertEqual(summary["unread"], 1)
        self.assertEqual(summary["ending_locked"], 1)

    def test_dict_roundtrip(self) -> None:
        progress = ProgressState()
        progress.mark_seen("start")
        progress.mark_chosen("a", "b")
        restored = ProgressState.from_dict(progress.to_dict())
        self.assertEqual(restored.to_dict(), progress.to_dict())

    def test_store_roundtrip(self) -> None:
        progress = ProgressState()
        progress.mark_seen("a")
        restored = ProgressState.from_store(progress.to_store())
        self.assertEqual(restored.to_dict(), progress.to_dict())

    def test_from_kernel(self) -> None:
        graph = make_graph()
        kernel = kernel_for_graph(graph)
        kernel.mark_seen("start")
        progress = ProgressState.from_kernel(kernel)
        self.assertIn("start", progress.seen)


class RuntimeSourceTests(unittest.TestCase):
    def test_source_is_embeddable(self) -> None:
        source = runtime_kernel_source()
        self.assertIn("class PGFKernel", source)
        lines = [line.strip() for line in source.splitlines()]
        self.assertFalse(any(line.startswith("from __future__") for line in lines))
        self.assertFalse(any(line.startswith("import ") for line in lines))

    def test_source_compiles(self) -> None:
        namespace: dict[str, object] = {}
        exec(compile(runtime_kernel_source(), "<pgf_runtime>", "exec"), namespace)
        self.assertIn("PGFKernel", namespace)


if __name__ == "__main__":
    unittest.main()
