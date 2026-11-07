"""Contracts shared between :mod:`pgf_core` and engine adapters.

Adapters are discovered through the ``pgf.adapters`` entry point group (or the
``PGF_ADAPTERS`` environment variable for development checkouts).  The core
only ever talks to an adapter through the small protocol and data classes in
this module, so the CLI has no import-time dependency on any adapter.
"""

from __future__ import annotations

import importlib
import importlib.metadata
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from .errors import AdapterError
from .layout import Layout
from .model import FlowGraph

__all__ = [
    "AdapterInfo",
    "StoryResult",
    "StyleResult",
    "EntryResult",
    "GeneratedArtifact",
    "EmitResult",
    "InstallResult",
    "StepOutcome",
    "ChainReport",
    "Adapter",
    "AdapterRegistry",
    "load_adapters",
]


@dataclass
class AdapterInfo:
    name: str
    engine: str
    game_name: str
    base_dir: Path
    game_dir: Path
    engine_version: str = ""
    game_version: str = ""
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class StoryResult:
    graph: FlowGraph
    warnings: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    stats: dict[str, Any] = field(default_factory=dict)
    source: str = "script"

    def summary(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "graph": self.graph.stats(),
            "warnings": len(self.warnings),
            "stats": self.stats,
        }


@dataclass
class StyleResult:
    tokens: Any
    warnings: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    evidence: dict[str, Any] = field(default_factory=dict)

    def summary(self) -> dict[str, Any]:
        tokens = self.tokens
        return {
            "name": getattr(tokens, "name", ""),
            "source": getattr(tokens, "source", ""),
            "confidence": getattr(tokens, "confidence", 0.0),
            "evidence": self.evidence,
            "warnings": len(self.warnings),
        }


@dataclass
class EntryResult:
    mode: str
    available: bool = True
    reason: str = ""
    position: tuple[int, int] = (0, 0)
    size: tuple[int, int] = (0, 0)
    hotkey: tuple[str, ...] = ()
    warnings: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    payload: Any = None

    def summary(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "available": self.available,
            "reason": self.reason,
            "position": list(self.position),
            "size": list(self.size),
            "hotkey": list(self.hotkey),
            "warnings": len(self.warnings),
        }


@dataclass
class GeneratedArtifact:
    name: str
    content: str = ""
    role: str = "file"
    data: bytes | None = None

    @property
    def is_binary(self) -> bool:
        return self.data is not None

    @property
    def payload(self) -> bytes:
        return self.data if self.data is not None else self.content.encode("utf-8")

    @property
    def byte_size(self) -> int:
        return len(self.payload)


@dataclass
class EmitResult:
    artifacts: list[GeneratedArtifact] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def summary(self) -> dict[str, Any]:
        return {
            "files": [{"name": a.name, "bytes": a.byte_size, "role": a.role} for a in self.artifacts],
            "warnings": len(self.warnings),
        }


@dataclass
class InstallResult:
    written: list[str] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    manifest_path: Path | None = None
    dry_run: bool = False

    @property
    def ok(self) -> bool:
        return not self.errors

    def summary(self) -> dict[str, Any]:
        return {
            "written": list(self.written),
            "removed": list(self.removed),
            "skipped": list(self.skipped),
            "warnings": list(self.warnings),
            "errors": list(self.errors),
            "manifest": str(self.manifest_path) if self.manifest_path else None,
            "dry_run": self.dry_run,
        }


STATUS_SUCCESS = "success"
STATUS_UNAVAILABLE = "unavailable"
STATUS_FAILED = "failed"
STATUS_SKIPPED = "skipped"


@dataclass
class StepOutcome:
    step: str
    status: str
    message: str = ""
    details: dict[str, Any] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.status == STATUS_SUCCESS

    def summary(self) -> dict[str, Any]:
        return {
            "step": self.step,
            "status": self.status,
            "message": self.message,
            "details": self.details,
        }


@dataclass
class ChainReport:
    name: str
    outcomes: list[StepOutcome] = field(default_factory=list)
    chosen: str = ""

    def add(self, step: str, status: str, message: str = "", **details: Any) -> StepOutcome:
        outcome = StepOutcome(step, status, message, dict(details))
        self.outcomes.append(outcome)
        if status == STATUS_SUCCESS and not self.chosen:
            self.chosen = step
        return outcome

    @property
    def ok(self) -> bool:
        return bool(self.chosen)

    def summary(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "chosen": self.chosen,
            "outcomes": [outcome.summary() for outcome in self.outcomes],
        }


class Adapter(Protocol):
    """The contract every engine adapter implements."""

    name: str
    engine: str

    def detect(self, path: Path) -> AdapterInfo | None: ...

    def build_story(
        self,
        info: AdapterInfo,
        *,
        entry_label: str = "start",
        include_side_labels: bool = False,
    ) -> StoryResult: ...

    def screenshot_graph(self, info: AdapterInfo) -> StoryResult | None: ...

    def preset_graph(self, info: AdapterInfo) -> StoryResult: ...

    def build_style(self, info: AdapterInfo, *, preset: str = "paper_dark") -> StyleResult: ...

    def screenshot_style(self, info: AdapterInfo) -> StyleResult | None: ...

    def plan_entry(
        self,
        info: AdapterInfo,
        graph: FlowGraph,
        tokens: Any,
        *,
        mode: str,
        options: dict[str, Any] | None = None,
    ) -> EntryResult: ...

    def emit(
        self,
        info: AdapterInfo,
        graph: FlowGraph,
        layout: Layout,
        tokens: Any,
        entry: EntryResult,
        *,
        options: dict[str, Any] | None = None,
    ) -> EmitResult: ...

    def install(
        self,
        info: AdapterInfo,
        artifacts: list[GeneratedArtifact],
        *,
        meta: dict[str, Any] | None = None,
        force: bool = False,
        dry_run: bool = False,
    ) -> InstallResult: ...

    def uninstall(
        self,
        info: AdapterInfo,
        *,
        force: bool = False,
        dry_run: bool = False,
    ) -> InstallResult: ...

    def close(self) -> None: ...


class AdapterRegistry:
    def __init__(self) -> None:
        self._adapters: dict[str, Adapter] = {}
        self.sources: list[str] = []

    def register(self, adapter: Adapter, source: str = "") -> None:
        name = getattr(adapter, "name", "") or adapter.__class__.__name__
        self._adapters[name] = adapter
        if source:
            self.sources.append(source)

    def load_entry_points(self) -> None:
        try:
            points = importlib.metadata.entry_points(group="pgf.adapters")
        except TypeError:  # pragma: no cover - very old importlib.metadata
            points = importlib.metadata.entry_points().get("pgf.adapters", [])  # type: ignore[attr-defined]
        for point in points:
            try:
                factory = point.load()
            except Exception as exc:  # pragma: no cover - broken install
                raise AdapterError(f"could not load adapter entry point {point.name}: {exc}") from exc
            adapter = factory() if isinstance(factory, type) else factory
            self.register(adapter, f"entry point {point.name}")

    def load_environment(self) -> None:
        spec = os.environ.get("PGF_ADAPTERS", "").strip()
        if not spec:
            return
        for item in spec.split(","):
            item = item.strip()
            if not item:
                continue
            module_name, _, attribute = item.partition(":")
            try:
                module = importlib.import_module(module_name)
                factory = getattr(module, attribute or "ADAPTER")
            except (ImportError, AttributeError) as exc:
                raise AdapterError(f"could not load adapter {item!r}: {exc}") from exc
            adapter = factory() if isinstance(factory, type) else factory
            self.register(adapter, f"environment {item}")

    def names(self) -> tuple[str, ...]:
        return tuple(sorted(self._adapters))

    def get(self, name: str = "") -> Adapter:
        if not name:
            if len(self._adapters) == 1:
                return next(iter(self._adapters.values()))
            if not self._adapters:
                raise AdapterError(
                    "no PaperGalFlow adapters are registered. Install the package "
                    "(pip install -e .) or set PGF_ADAPTERS=module:Class"
                )
            raise AdapterError(
                "several adapters are registered; choose one of: " + ", ".join(self.names())
            )
        try:
            return self._adapters[name]
        except KeyError as exc:
            raise AdapterError(
                f"unknown adapter {name!r}; available: " + (", ".join(self.names()) or "none")
            ) from exc

    def __len__(self) -> int:
        return len(self._adapters)


def load_adapters() -> AdapterRegistry:
    registry = AdapterRegistry()
    registry.load_entry_points()
    registry.load_environment()
    return registry
