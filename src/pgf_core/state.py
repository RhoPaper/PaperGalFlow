"""Node states, host side progress bookkeeping and the runtime kernel bridge.

The state machine that runs inside the patched game lives in
``pgf_core/runtime/pgf_runtime.py``.  This module imports that file, exposes it
as :class:`RuntimeStateKernel` and adds the host side conveniences the CLI and
tests need.  :func:`runtime_kernel_source` returns the very same source so the
adapter can embed it into the generated ``.rpy`` file -- one implementation,
two execution environments.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Mapping

from .model import FlowGraph

from .runtime.pgf_runtime import (  # noqa: E402  (intentional after docstring)
    PGF_RUNTIME_VERSION,
    PGFDictStore,
    PGFKernel,
)

RuntimeStateKernel = PGFKernel

_RUNTIME_FILE = Path(__file__).with_name("runtime") / "pgf_runtime.py"


class NodeState(str, Enum):
    """Visual state of a single flowchart node."""

    LOCKED = "locked"
    UNREAD = "unread"
    READ = "read"
    ENDING_LOCKED = "ending_locked"
    ENDING_READ = "ending_read"

    @property
    def is_locked(self) -> bool:
        return self in (NodeState.LOCKED, NodeState.ENDING_LOCKED)

    @property
    def is_read(self) -> bool:
        return self in (NodeState.READ, NodeState.ENDING_READ)

    @property
    def is_ending(self) -> bool:
        return self in (NodeState.ENDING_LOCKED, NodeState.ENDING_READ)

    @property
    def title_hidden(self) -> bool:
        return self.is_locked


def runtime_kernel_source() -> str:
    """Return the embeddable runtime kernel source (without ``__future__``)."""

    source = _RUNTIME_FILE.read_text(encoding="utf-8")
    if any(line.lstrip().startswith("from __future__") for line in source.splitlines()):
        raise RuntimeError("runtime kernel must not use __future__ imports")
    return source


def kernel_for_graph(graph: FlowGraph, store: PGFDictStore | None = None) -> PGFKernel:
    """Build a runtime kernel for ``graph`` backed by an in-memory store."""

    node_ids = tuple(graph.nodes)
    edges = tuple((edge.source, edge.target, edge.kind.value) for edge in graph.edges)
    label_map: dict[str, list[str]] = {}
    for node in graph.nodes.values():
        targets = label_map.setdefault(str(node.meta.get("label", node.id)), [])
        targets.append(node.id)
    return PGFKernel(
        store if store is not None else PGFDictStore(),
        graph.entry,
        node_ids,
        graph.endings(),
        edges,
        label_map=label_map,
    )


@dataclass
class ProgressState:
    """Host side mirror of the persistent progress structure.

    Used by the CLI's ``inspect``/``stats`` commands and by tests.  All state
    transitions are delegated to the real runtime kernel so the host and the
    game can never disagree about what "unread" means.
    """

    seen: set[str] = field(default_factory=set)
    chosen: set[tuple[str, str]] = field(default_factory=set)
    version: int = PGF_RUNTIME_VERSION

    # -- mutation ------------------------------------------------------------
    def mark_seen(self, *node_ids: str) -> None:
        self.seen.update(node_ids)

    def mark_chosen(self, source: str, target: str) -> None:
        self.chosen.add((source, target))

    def reset(self) -> None:
        self.seen.clear()
        self.chosen.clear()

    # -- queries -------------------------------------------------------------
    def resolve(self, graph: FlowGraph) -> dict[str, NodeState]:
        store = PGFDictStore(self.to_store())
        kernel = kernel_for_graph(graph, store)
        return {node_id: NodeState(value) for node_id, value in kernel.states().items()}

    def summary(self, graph: FlowGraph) -> dict[str, int]:
        states = self.resolve(graph)
        counts = {
            "read": 0,
            "unread": 0,
            "locked": 0,
            "ending_locked": 0,
            "ending_read": 0,
        }
        for state in states.values():
            counts[state.value] += 1
        counts["total"] = len(states)
        return counts

    # -- serialisation -------------------------------------------------------
    def to_store(self) -> dict[str, Any]:
        return {
            "pgf_progress": {
                "v": self.version,
                "seen": sorted(self.seen),
                "chosen": sorted(a + "\x1f" + b for a, b in self.chosen),
            }
        }

    @classmethod
    def from_store(cls, data: Mapping[str, Any]) -> "ProgressState":
        raw = data.get("pgf_progress", {}) if data else {}
        if not isinstance(raw, Mapping):
            return cls()
        seen = {str(item) for item in raw.get("seen", ())}
        chosen: set[tuple[str, str]] = set()
        for item in raw.get("chosen", ()):
            parts = str(item).split("\x1f", 1)
            if len(parts) == 2:
                chosen.add((parts[0], parts[1]))
        return cls(seen=seen, chosen=chosen)

    @classmethod
    def from_kernel(cls, kernel: PGFKernel) -> "ProgressState":
        raw = kernel.store.get(kernel.key, {})
        return cls.from_store({"pgf_progress": raw})

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "seen": sorted(self.seen),
            "chosen": sorted([a, b] for a, b in self.chosen),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ProgressState":
        seen = {str(item) for item in data.get("seen", ())}
        chosen = {(str(pair[0]), str(pair[1])) for pair in data.get("chosen", ()) if len(pair) == 2}
        return cls(seen=seen, chosen=chosen)
