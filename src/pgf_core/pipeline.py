"""The degradation chains and the end-to-end generation pipeline.

The core, not the adapter, decides what happens when a source is unavailable:

* story chain: ``script`` -> ``screenshot`` -> ``preset``
* style chain: ``game`` -> ``screenshot`` -> ``preset``
* entry chain: ``quick_menu_patch`` -> ``ai_rewrite`` -> ``overlay_button``

Adapters report success or failure for a single step; they never implement
fallbacks themselves.  The hotkey screen is part of every entry plan, so it
stays available no matter which visual entrance wins.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any

from .adapter import (
    STATUS_FAILED,
    STATUS_SUCCESS,
    STATUS_UNAVAILABLE,
    Adapter,
    AdapterInfo,
    ChainReport,
    EmitResult,
    EntryResult,
    StoryResult,
    StyleResult,
)
from .errors import PipelineError
from .layout import Layout, compute_layout

__all__ = [
    "PipelineOptions",
    "PipelineReport",
    "Pipeline",
    "STORY_CHAIN",
    "STYLE_CHAIN",
    "ENTRY_CHAIN",
    "write_artifacts",
]

STORY_CHAIN = ("script", "screenshot", "preset")
STYLE_CHAIN = ("game", "screenshot", "preset")
ENTRY_CHAIN = ("quick_menu_patch", "ai_rewrite", "overlay_button")


@dataclass
class PipelineOptions:
    path: Path
    adapter: str = ""
    entry_label: str = "start"
    include_side_labels: bool = False
    show_condition_labels: bool = False
    style_preset: str = "paper_dark"
    entry_mode: str = ""
    title: str = ""
    theme_path: str = ""

    def normalized(self) -> "PipelineOptions":
        return PipelineOptions(
            path=Path(self.path).expanduser().resolve(),
            adapter=self.adapter.strip(),
            entry_label=self.entry_label.strip() or "start",
            include_side_labels=bool(self.include_side_labels),
            show_condition_labels=bool(self.show_condition_labels),
            style_preset=self.style_preset.strip() or "paper_dark",
            entry_mode=self.entry_mode.strip(),
            title=self.title.strip(),
            theme_path=self.theme_path.strip(),
        )


@dataclass
class PipelineReport:
    options: PipelineOptions
    info: AdapterInfo
    story: StoryResult
    style: StyleResult
    entry: EntryResult
    layout: Layout
    emitted: EmitResult
    chains: dict[str, ChainReport] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def artifacts(self):
        return self.emitted.artifacts

    def summary(self) -> dict[str, Any]:
        info = self.info
        return {
            "game": info.game_name,
            "engine": info.engine,
            "engine_version": info.engine_version,
            "basedir": str(info.base_dir),
            "game_dir": str(info.game_dir),
            "entry_label": self.options.entry_label,
            "chains": {name: chain.summary() for name, chain in self.chains.items()},
            "story": self.story.summary(),
            "style": self.style.summary(),
            "entry": self.entry.summary(),
            "layout": {
                "width": self.layout.width,
                "height": self.layout.height,
                "layers": len(self.layout.layers),
                "nodes": len(self.layout.positions),
                "edges": len(self.layout.edges),
            },
            "files": [{"name": a.name, "bytes": a.byte_size, "role": a.role} for a in self.artifacts],
            "warnings": list(self.warnings),
            "notes": list(self.notes),
        }


def _append_unique(target: list[str], values: list[str]) -> None:
    for value in values:
        text = str(value).strip()
        if text and text not in target:
            target.append(text)


class Pipeline:
    def __init__(self, adapter: Adapter, options: PipelineOptions) -> None:
        self.adapter = adapter
        self.options = options.normalized()
        self.warnings: list[str] = []
        self.notes: list[str] = []

    def run(self) -> PipelineReport:
        info = self.adapter.detect(self.options.path)
        if info is None:
            raise PipelineError(
                f"{self.options.path} does not look like a game supported by "
                f"the {getattr(self.adapter, 'engine', 'selected')} adapter"
            )

        story, story_chain = self._story_chain(info)
        style, style_chain = self._style_chain(info)
        style = self._apply_theme(style, style_chain)
        layout = compute_layout(story.graph)
        entry, entry_chain = self._entry_chain(info, story, style)
        emitted = self.adapter.emit(
            info,
            story.graph,
            layout,
            style.tokens,
            entry,
            options={
                "show_condition_labels": self.options.show_condition_labels,
                "entry_label": self.options.entry_label,
                "title": self.options.title,
            },
        )

        for result in (story, style, entry, emitted):
            _append_unique(self.warnings, list(getattr(result, "warnings", [])))
            _append_unique(self.notes, list(getattr(result, "notes", [])))

        if not emitted.artifacts:
            raise PipelineError("the adapter did not generate any files")

        return PipelineReport(
            options=self.options,
            info=info,
            story=story,
            style=style,
            entry=entry,
            layout=layout,
            emitted=emitted,
            chains={"story": story_chain, "style": style_chain, "entry": entry_chain},
            warnings=self.warnings,
            notes=self.notes,
        )

    # -- theme ---------------------------------------------------------------
    def _apply_theme(self, style: StyleResult, chain: ChainReport) -> StyleResult:
        if not self.options.theme_path:
            return style
        from .theme import ThemeError, apply_theme, load_theme

        try:
            theme = load_theme(self.options.theme_path)
            tokens = apply_theme(style.tokens, theme)
        except ThemeError as exc:
            raise PipelineError(str(exc)) from exc
        style.tokens = tokens
        style.notes.append(f"theme applied: {theme.name or theme.source}")
        chain.add(
            "theme",
            STATUS_SUCCESS,
            f"theme {theme.name or 'custom'}",
            path=theme.source,
            source=tokens.source,
        )
        return style

    # -- chains --------------------------------------------------------------
    def _story_chain(self, info: AdapterInfo) -> tuple[StoryResult, ChainReport]:
        chain = ChainReport("story")
        result: StoryResult | None = None
        for step in STORY_CHAIN:
            try:
                if step == "script":
                    candidate = self.adapter.build_story(
                        info,
                        entry_label=self.options.entry_label,
                        include_side_labels=self.options.include_side_labels,
                    )
                    message = f"{candidate.graph.stats()['nodes']} nodes from game scripts"
                elif step == "screenshot":
                    candidate = self.adapter.screenshot_graph(info)
                    message = "AI screenshot analysis is not configured"
                else:
                    candidate = self.adapter.preset_graph(info)
                    message = "using the minimal preset graph"
            except Exception as exc:  # adapter bug or unreadable game
                chain.add(step, STATUS_FAILED, str(exc))
                continue
            if candidate is None:
                chain.add(step, STATUS_UNAVAILABLE, message)
                continue
            chain.add(step, STATUS_SUCCESS, message, nodes=candidate.graph.stats()["nodes"])
            result = candidate
            break
        if result is None:
            raise PipelineError("no story source was available: " + self._describe(chain))
        return result, chain

    def _style_chain(self, info: AdapterInfo) -> tuple[StyleResult, ChainReport]:
        from pgf_style import preset_tokens

        chain = ChainReport("style")
        result: StyleResult | None = None
        for step in STYLE_CHAIN:
            try:
                if step == "game":
                    candidate = self.adapter.build_style(info, preset=self.options.style_preset)
                    message = (
                        f"style {getattr(candidate.tokens, 'name', '')} from "
                        f"{getattr(candidate.tokens, 'source', '')}"
                    )
                elif step == "screenshot":
                    candidate = self.adapter.screenshot_style(info)
                    message = "AI screenshot analysis is not configured"
                else:
                    tokens = preset_tokens(self.options.style_preset)
                    candidate = StyleResult(tokens=tokens, notes=["using the built-in preset style"])
                    message = f"built-in preset {tokens.name}"
            except Exception as exc:
                chain.add(step, STATUS_FAILED, str(exc))
                continue
            if candidate is None:
                chain.add(step, STATUS_UNAVAILABLE, message)
                continue
            chain.add(
                step,
                STATUS_SUCCESS,
                message,
                confidence=getattr(candidate.tokens, "confidence", 0.0),
            )
            result = candidate
            break
        if result is None:  # pragma: no cover - the preset cannot fail
            raise PipelineError("no style source was available: " + self._describe(chain))
        return result, chain

    def _entry_chain(
        self, info: AdapterInfo, story: StoryResult, style: StyleResult
    ) -> tuple[EntryResult, ChainReport]:
        chain = ChainReport("entry")
        order = (self.options.entry_mode,) if self.options.entry_mode else ENTRY_CHAIN
        result: EntryResult | None = None
        for step in order:
            try:
                candidate = self.adapter.plan_entry(
                    info,
                    story.graph,
                    style.tokens,
                    mode=step,
                    options={"entry_label": self.options.entry_label},
                )
            except Exception as exc:
                chain.add(step, STATUS_FAILED, str(exc))
                continue
            if candidate is None or not candidate.available:
                reason = candidate.reason if candidate is not None else "not available"
                chain.add(step, STATUS_UNAVAILABLE, reason)
                continue
            chain.add(step, STATUS_SUCCESS, candidate.reason or step, mode=candidate.mode)
            result = candidate
            break
        if result is None:
            raise PipelineError("no entry point could be installed: " + self._describe(chain))
        # The hotkey is bundled with every entry plan.
        chain.add(
            "hotkey",
            STATUS_SUCCESS,
            "热键 " + ", ".join(result.hotkey) if result.hotkey else "hotkey bundled",
            keys=list(result.hotkey),
        )
        return result, chain

    @staticmethod
    def _describe(chain: ChainReport) -> str:
        return "; ".join(
            f"{outcome.step}: {outcome.status}" + (f" ({outcome.message})" if outcome.message else "")
            for outcome in chain.outcomes
        )


def write_artifacts(out_dir: Path, artifacts: list[Any]) -> list[Path]:
    """Write generated artifacts (text or binary) to a plain output directory."""

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for artifact in artifacts:
        name = str(getattr(artifact, "name", ""))
        relative = PurePosixPath(name)
        if (
            not name
            or "\\" in name
            or relative.is_absolute()
            or any(part in ("", ".", "..") for part in relative.parts)
            or name.startswith(".")
        ):
            raise PipelineError(f"refusing unsafe artifact name: {name!r}")
        target = out_dir.joinpath(*relative.parts)
        target.parent.mkdir(parents=True, exist_ok=True)
        data = getattr(artifact, "data", None)
        if data is not None:
            target.write_bytes(data)
        else:
            target.write_text(str(getattr(artifact, "content", "")), encoding="utf-8", newline="\n")
        written.append(target)
    return written
