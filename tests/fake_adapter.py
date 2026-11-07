from __future__ import annotations

from pathlib import Path

from pgf_core.adapter import (
    AdapterInfo,
    EmitResult,
    EntryResult,
    GeneratedArtifact,
    InstallResult,
    StoryResult,
    StyleResult,
)
from pgf_core.errors import AdapterError
from pgf_core.model import EdgeKind, FlowGraph, FlowNode, NodeKind
from pgf_style import preset_tokens


def tiny_graph() -> FlowGraph:
    graph = FlowGraph(entry="start")
    graph.add_node(FlowNode("start", NodeKind.ENTRY, title="开始", meta={"label": "start"}))
    graph.add_node(FlowNode("end", NodeKind.ENDING, title="结束", meta={"label": "start"}))
    graph.connect("start", "end", EdgeKind.END)
    return graph


class FakeAdapter:
    name = "fake"
    engine = "Fake"

    def detect(self, path: Path) -> AdapterInfo:
        path = Path(path).resolve()
        return AdapterInfo(
            name=self.name,
            engine=self.engine,
            game_name="Fake Game",
            base_dir=path,
            game_dir=path,
            engine_version="1.0",
        )

    def build_story(self, info, *, entry_label="start", include_side_labels=False):
        raise AdapterError("fake game has no scripts")

    def screenshot_graph(self, info):
        return None

    def preset_graph(self, info):
        return StoryResult(graph=tiny_graph(), source="preset", notes=["fake preset"])

    def build_style(self, info, *, preset="paper_dark", screenshots=(), vision_options=None):
        raise AdapterError("fake game has no GUI")

    def screenshot_style(self, info, *, screenshots=(), vision_options=None, preset="paper_dark"):
        return None

    def plan_entry(self, info, graph, tokens, *, mode, options=None):
        if mode == "overlay_button":
            return EntryResult(mode=mode, available=True, reason="fake overlay", hotkey=("K_F10",))
        return EntryResult(mode=mode, available=False, reason="not available in fake")

    def emit(self, info, graph, layout, tokens, entry, *, options=None):
        return EmitResult(
            artifacts=[GeneratedArtifact("pgf_flowchart_screen.rpy", "# PaperGalFlow fake\n", "screen")]
        )

    def install(self, info, artifacts, *, meta=None, force=False, dry_run=False):
        return InstallResult(written=[a.name for a in artifacts], dry_run=dry_run)

    def uninstall(self, info, *, force=False, dry_run=False):
        return InstallResult(dry_run=dry_run)

    def verify_install(self, info):
        return []

    def close(self):
        pass
