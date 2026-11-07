"""The Ren'Py adapter: wires parsing, style probing, emission and installation.

All engine specific work lives behind the :class:`pgf_core.adapter.Adapter`
protocol.  The core drives the degradation chains; this class only answers
"can I do this step?" for each request.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path
from typing import Any

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
from pgf_core.layout import Layout
from pgf_core.model import FlowGraph, FlowNode, NodeKind
from pgf_core.version import __version__
from pgf_style import StyleTokens, tokens_from_evidence

from .analyze import AnalyzeOptions, AnalyzeResult, build_graph
from .archive import ArchiveError, GameArchive
from .assets import build_ui_assets
from .entry import EntryOptions, build_entry_plan
from .installer import install_files, uninstall_files, verify_install
from .screen_emit import FlowchartEmitOptions, GeneratedFile, emit_flowchart_screen
from .script_model import ScriptFile
from .style_probe import StyleProbeResult, probe_style

__all__ = ["RenPyAdapter", "ADAPTER"]

_LOG_VERSION_RE = re.compile(r"Ren'Py\s+([^\s]+)")
_QUOTED_RE = re.compile(r"""["']([^"']+)["']""")

def _read_log_meta(base_dir: Path) -> tuple[str, str]:
    log = base_dir / "log.txt"
    engine = ""
    game_version = ""
    if not log.is_file():
        return engine, game_version
    try:
        lines = log.read_text(encoding="utf-8", errors="replace").splitlines()[:12]
    except OSError:
        return engine, game_version
    for index, line in enumerate(lines):
        match = _LOG_VERSION_RE.search(line)
        if match and not engine:
            engine = match.group(1)
        if index >= 3 and re.fullmatch(r"\d+(?:\.\d+)+", line.strip()) and not game_version:
            game_version = line.strip()
    return engine, game_version


def _define_string(raw: str) -> str:
    text = raw.strip()
    try:
        value = ast.literal_eval(text)
    except (ValueError, SyntaxError):
        match = _QUOTED_RE.search(text)
        return match.group(1) if match else ""
    return value if isinstance(value, str) else ""


class RenPyAdapter:
    name = "renpy"
    engine = "Ren'Py"

    def __init__(self) -> None:
        self._info: AdapterInfo | None = None
        self._archive: GameArchive | None = None
        self._scripts: list[ScriptFile] = []
        self._analysis: AnalyzeResult | None = None
        self._probe: StyleProbeResult | None = None
        self._tokens: StyleTokens | None = None
        self._entry_plan = None

    # -- detection -----------------------------------------------------------
    def detect(self, path: Path) -> AdapterInfo | None:
        path = Path(path).expanduser().resolve()
        if path.is_file():
            path = path.parent
        if (path / "game").is_dir() and path.name != "game":
            base_dir = path
            game_dir = path / "game"
        elif path.name == "game" and path.is_dir():
            base_dir = path.parent
            game_dir = path
        elif path.is_dir() and any(path.glob("*.rpa")):
            base_dir = path.parent
            game_dir = path
        else:
            return None
        if not game_dir.is_dir():
            return None
        has_renpy = (base_dir / "renpy").is_dir() or (base_dir / "lib").is_dir()
        has_scripts = bool(list(game_dir.glob("*.rpa"))) or any(game_dir.glob("*.rpy")) or any(
            game_dir.glob("*.rpyc")
        )
        if not has_scripts:
            return None
        engine_version, game_version = _read_log_meta(base_dir)
        info = AdapterInfo(
            name=self.name,
            engine=self.engine,
            game_name=base_dir.name,
            base_dir=base_dir,
            game_dir=game_dir,
            engine_version=engine_version,
            game_version=game_version,
            extra={"has_renpy_runtime": has_renpy},
        )
        self._info = info
        return info

    # -- story ---------------------------------------------------------------
    def _ensure_archive(self, info: AdapterInfo) -> GameArchive:
        if self._archive is None:
            try:
                self._archive = GameArchive.open(info.game_dir)
            except ArchiveError as exc:
                raise AdapterError(str(exc)) from exc
        return self._archive

    def _ensure_scripts(self, info: AdapterInfo) -> list[ScriptFile]:
        if not self._scripts:
            archive = self._ensure_archive(info)
            parsed = archive.parse_all()
            self._scripts = list(parsed.values())
            if archive.warnings:
                info.extra["archive_warnings"] = list(archive.warnings)
            formats: dict[str, int] = {}
            for script in self._scripts:
                formats[script.source_format] = formats.get(script.source_format, 0) + 1
            info.extra["source_files"] = len(self._scripts)
            info.extra["source_formats"] = formats
            self._apply_game_meta(info, self._scripts)
        return self._scripts

    def _apply_game_meta(self, info: AdapterInfo, scripts: list[ScriptFile]) -> None:
        for script in scripts:
            defines = script.defines()
            for key in ("config.name", "config.version"):
                if key not in defines:
                    continue
                value = _define_string(defines[key])
                if not value:
                    continue
                if key == "config.name":
                    info.game_name = value
                else:
                    info.game_version = value

    def build_story(
        self,
        info: AdapterInfo,
        *,
        entry_label: str = "start",
        include_side_labels: bool = False,
    ) -> StoryResult:
        scripts = self._ensure_scripts(info)
        if not scripts:
            raise AdapterError("no Ren'Py scripts were found in the game")
        options = AnalyzeOptions(
            entry_label=entry_label,
            include_side_labels=include_side_labels,
        )
        analysis = build_graph(scripts, options)
        if not analysis.graph.nodes:
            raise AdapterError("the story graph is empty; no labels could be analysed")
        self._analysis = analysis
        info.extra["labels"] = analysis.label_count
        info.extra["entry_node"] = analysis.graph.entry
        notes = list(analysis.notes)
        return StoryResult(
            graph=analysis.graph,
            warnings=list(analysis.warnings),
            notes=notes,
            source="script",
            stats={
                "scripts": analysis.script_count,
                "labels": analysis.label_count,
                "endings": len(analysis.graph.endings()),
                "source_formats": dict(info.extra.get("source_formats", {})),
            },
        )

    def screenshot_graph(self, info: AdapterInfo) -> StoryResult | None:
        return None

    def preset_graph(self, info: AdapterInfo) -> StoryResult:
        graph = FlowGraph(entry="pgf_preset_entry")
        graph.add_node(
            FlowNode(
                "pgf_preset_entry",
                NodeKind.ENTRY,
                title=info.game_name or "剧情流程图",
                subtitle="preset",
                meta={"label": ""},
            )
        )
        return StoryResult(
            graph=graph,
            warnings=["故事脚本无法解析；已生成仅含入口的占位流程图"],
            notes=["preset graph fallback"],
            source="preset",
        )

    # -- style ---------------------------------------------------------------
    def build_style(self, info: AdapterInfo, *, preset: str = "paper_dark") -> StyleResult:
        scripts = self._ensure_scripts(info)
        archive = self._ensure_archive(info)
        probe = probe_style(scripts, archive)
        tokens = tokens_from_evidence(probe.evidence, preset=preset)
        self._probe = probe
        self._tokens = tokens
        info.extra["style_source"] = tokens.source
        info.extra["style_confidence"] = round(tokens.confidence, 3)
        info.extra["screen_size"] = list(probe.evidence.screen_size) if probe.evidence.screen_size else None
        if probe.quick_menu is not None:
            info.extra["quick_menu"] = {
                "found": probe.quick_menu.found,
                "buttons": probe.quick_menu.button_count,
                "has_source": probe.quick_menu.has_source,
                "bbox": list(probe.quick_menu.bbox) if probe.quick_menu.bbox else None,
            }
        warnings = list(probe.warnings)
        return StyleResult(
            tokens=tokens,
            warnings=warnings,
            notes=list(probe.notes),
            evidence={
                **probe.evidence.summary(),
                "samples": [sample.to_dict() for sample in probe.evidence.ui_samples],
            },
        )

    def screenshot_style(self, info: AdapterInfo) -> StyleResult | None:
        return None

    # -- entry ---------------------------------------------------------------
    def plan_entry(
        self,
        info: AdapterInfo,
        graph: FlowGraph,
        tokens: Any,
        *,
        mode: str,
        options: dict[str, Any] | None = None,
    ) -> EntryResult:
        if not isinstance(tokens, StyleTokens):
            raise AdapterError("the Ren'Py adapter needs pgf-style tokens")
        if self._probe is None:
            self.build_style(info)
        probe = self._probe
        assert probe is not None
        screen_size = probe.evidence.screen_size

        if mode == "ai_rewrite":
            return EntryResult(
                mode=mode,
                available=False,
                reason="AI 辅助改写需要外部的视觉/语言模型后端，本版本未配置",
            )
        if mode == "quick_menu_patch":
            quick = probe.quick_menu
            if quick is None or not quick.found or not quick.has_source or not quick.source.strip():
                return EntryResult(
                    mode=mode,
                    available=False,
                    reason="quick_menu 只有编译后的 .rpyc，无法安全地按源码追加按钮",
                )
            plan = build_entry_plan(
                tokens,
                quick,
                EntryOptions(
                    game_name=info.game_name,
                    screen_size=screen_size,
                    prefer_quick_menu_patch=True,
                    force_mode="quick_menu_patch",
                ),
            )
            if not plan.patched_quick_menu:
                return EntryResult(mode=mode, available=False, reason=plan.reason)
        elif mode in ("overlay_button", "hotkey"):
            plan = build_entry_plan(
                tokens,
                probe.quick_menu,
                EntryOptions(
                    game_name=info.game_name,
                    screen_size=screen_size,
                    force_mode="overlay_button",
                ),
            )
        else:
            return EntryResult(mode=mode, available=False, reason=f"未知入口模式 {mode!r}")

        self._entry_plan = plan
        entry_options = options or {}
        entry_label = str(entry_options.get("entry_label", ""))
        return EntryResult(
            mode=plan.mode,
            available=True,
            reason=plan.reason,
            position=plan.position,
            size=plan.size,
            hotkey=plan.hotkey,
            warnings=list(plan.warnings),
            notes=list(plan.notes),
            payload=plan,
        )

    # -- emission ------------------------------------------------------------
    def emit(
        self,
        info: AdapterInfo,
        graph: FlowGraph,
        layout: Layout,
        tokens: Any,
        entry: EntryResult,
        *,
        options: dict[str, Any] | None = None,
    ) -> EmitResult:
        if not isinstance(tokens, StyleTokens):
            raise AdapterError("the Ren'Py adapter needs pgf-style tokens")
        options = options or {}
        probe = self._probe
        screen_size = probe.evidence.screen_size if probe is not None else None
        flowchart = emit_flowchart_screen(
            graph,
            layout,
            tokens,
            FlowchartEmitOptions(
                game_name=info.game_name,
                entry_label=str(options.get("entry_label", "")),
                screen_size=screen_size,
                show_condition_labels=bool(options.get("show_condition_labels", False)),
                version=__version__,
            ),
        )
        plan = entry.payload if entry.payload is not None else self._entry_plan
        if plan is None:
            raise AdapterError("no entry plan was produced")
        hook = plan.file
        artifacts = [
            GeneratedArtifact(flowchart.name, flowchart.content, "screen"),
            GeneratedArtifact(hook.name, hook.content, "entry"),
        ]
        ui_assets = build_ui_assets(tokens)
        artifacts.extend(
            GeneratedArtifact(asset.name, role=asset.role, data=asset.data)
            for asset in ui_assets
        )
        warnings = list(plan.warnings)
        notes = list(plan.notes)
        notes.append(f"entry mode: {entry.mode}")
        notes.append(f"generated {len(ui_assets)} nine-patch UI assets in pgf_ui/")
        return EmitResult(artifacts=artifacts, warnings=warnings, notes=notes)

    # -- installation --------------------------------------------------------
    def install(
        self,
        info: AdapterInfo,
        artifacts: list[GeneratedArtifact],
        *,
        meta: dict[str, Any] | None = None,
        force: bool = False,
        dry_run: bool = False,
    ) -> InstallResult:
        files = [
            GeneratedFile(a.name, a.content, a.role, data=a.data)
            for a in artifacts
        ]
        payload = {
            "game": info.game_name,
            "engine": info.engine,
            "engine_version": info.engine_version,
            "game_version": info.game_version,
            **(meta or {}),
        }
        report = install_files(info.game_dir, files, meta=payload, force=force, dry_run=dry_run)
        return InstallResult(
            written=list(report.written),
            removed=list(report.removed),
            skipped=list(report.skipped),
            warnings=list(report.warnings),
            errors=list(report.errors),
            manifest_path=report.manifest_path,
            dry_run=report.dry_run,
        )

    def uninstall(
        self,
        info: AdapterInfo,
        *,
        force: bool = False,
        dry_run: bool = False,
    ) -> InstallResult:
        report = uninstall_files(info.game_dir, force=force, dry_run=dry_run)
        return InstallResult(
            written=list(report.written),
            removed=list(report.removed),
            skipped=list(report.skipped),
            warnings=list(report.warnings),
            errors=list(report.errors),
            manifest_path=report.manifest_path,
            dry_run=report.dry_run,
        )

    def verify_install(self, info: AdapterInfo) -> list[str]:
        return verify_install(info.game_dir)

    def install_info(self, info: AdapterInfo) -> dict[str, Any]:
        from .installer import MANIFEST_NAME, read_manifest

        manifest = read_manifest(info.game_dir) or {}
        return {
            "installed": bool(manifest),
            "manifest": str(info.game_dir / MANIFEST_NAME),
            "version": manifest.get("version", ""),
            "created": manifest.get("created", ""),
            "entry_mode": manifest.get("entry_mode", ""),
            "style_source": manifest.get("style_source", ""),
            "files": [entry.get("name", "") for entry in manifest.get("files", []) if isinstance(entry, dict)],
            "problems": verify_install(info.game_dir),
        }

    # -- lifecycle -----------------------------------------------------------
    def close(self) -> None:
        if self._archive is not None:
            self._archive.close()
            self._archive = None


ADAPTER = RenPyAdapter
