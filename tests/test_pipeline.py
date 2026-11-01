from __future__ import annotations

import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

from pgf_core.cli import main as cli_main
from pgf_core.layout import compute_layout
from pgf_core.model import EdgeKind, FlowGraph, FlowNode, NodeKind
from pgf_core.pipeline import Pipeline, PipelineOptions, write_artifacts
from pgf_core.preview import render_html, render_svg
from pgf_core.state import ProgressState
from pgf_style import preset_tokens

from .fake_adapter import FakeAdapter
from .game_paths import game1_dir, has_game1


def view_graph() -> FlowGraph:
    graph = FlowGraph(entry="start")
    graph.add_node(FlowNode("start", NodeKind.ENTRY, title="开始", meta={"label": "start"}))
    graph.add_node(FlowNode("choice", NodeKind.CHOICE, title="选一个", meta={"label": "start"}))
    graph.add_node(FlowNode("end", NodeKind.ENDING, title="结束", meta={"label": "start"}))
    graph.connect("start", "choice")
    graph.connect("choice", "end", EdgeKind.CHOICE, label="继续")
    return graph


class PipelineTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.path = Path(self._tmp.name)

    def test_fake_adapter_uses_all_fallbacks(self) -> None:
        report = Pipeline(FakeAdapter(), PipelineOptions(path=self.path)).run()
        self.assertEqual(report.chains["story"].chosen, "preset")
        self.assertEqual(report.chains["style"].chosen, "preset")
        self.assertEqual(report.chains["entry"].chosen, "overlay_button")
        self.assertIn("hotkey", [outcome.step for outcome in report.chains["entry"].outcomes])
        self.assertEqual(report.story.graph.stats()["nodes"], 2)
        self.assertEqual(len(report.artifacts), 1)

    def test_write_artifacts(self) -> None:
        report = Pipeline(FakeAdapter(), PipelineOptions(path=self.path)).run()
        written = write_artifacts(self.path / "out", report.artifacts)
        self.assertEqual(len(written), 1)
        self.assertTrue(written[0].is_file())
        self.assertIn("PaperGalFlow", written[0].read_text(encoding="utf-8"))

    def test_unsafe_artifact_name_rejected(self) -> None:
        class Bad:
            name = "../evil.rpy"
            content = "x\n"

        with self.assertRaises(Exception):
            write_artifacts(self.path / "out", [Bad()])


@unittest.skipUnless(has_game1(), "test game 1 is not installed")
class RealPipelineTests(unittest.TestCase):
    def test_real_game_pipeline(self) -> None:
        from pgf_adapter_renpy.adapter import RenPyAdapter

        adapter = RenPyAdapter()
        try:
            report = Pipeline(
                adapter,
                PipelineOptions(path=game1_dir(), entry_label="start"),
            ).run()
        finally:
            adapter.close()
        self.assertEqual(report.chains["story"].chosen, "script")
        self.assertEqual(report.chains["style"].chosen, "game")
        self.assertIn(report.chains["entry"].chosen, ("quick_menu_patch", "overlay_button"))
        self.assertGreater(report.story.graph.stats()["nodes"], 20)
        names = {artifact.name for artifact in report.artifacts}
        self.assertEqual(names, {"pgf_flowchart_screen.rpy", "pgf_menu_hook.rpy"})


class CliTests(unittest.TestCase):
    def test_adapters_and_build_with_fake_adapter(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            out = root / "out"
            env = {"PGF_ADAPTERS": "tests.fake_adapter:FakeAdapter"}
            with mock.patch.dict(os.environ, env):
                buffer = io.StringIO()
                with redirect_stdout(buffer):
                    code = cli_main(["adapters", "--json"])
                self.assertEqual(code, 0)
                self.assertIn("fake", buffer.getvalue())
                with redirect_stdout(io.StringIO()):
                    code = cli_main(["build", str(root), "--out", str(out), "--json"])
                self.assertEqual(code, 0)
                self.assertTrue((out / "pgf_flowchart_screen.rpy").is_file())


class PreviewTests(unittest.TestCase):
    def test_svg_and_html(self) -> None:
        graph = view_graph()
        layout = compute_layout(graph)
        tokens = preset_tokens()
        progress = ProgressState()
        progress.mark_seen("start")
        states = {node_id: value.value for node_id, value in progress.resolve(graph).items()}
        svg = render_svg(graph, layout, tokens, states=states)
        self.assertIn("<svg", svg)
        self.assertIn("开始", svg)
        self.assertIn("？？？", svg)
        html = render_html(graph, layout, tokens, states=states, title="测试图")
        self.assertIn("<html", html)
        self.assertIn("测试图", html)
        self.assertIn("<svg", html)
        self.assertIn("PaperGalFlow", html)


if __name__ == "__main__":
    unittest.main()
