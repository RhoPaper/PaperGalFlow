"""Engine independent story graph model.

A :class:`FlowGraph` is the single intermediate representation every adapter
has to produce.  Nodes are *dramatic units* (a scene, a choice, an ending),
edges are transitions between them.  The model is intentionally boring: plain
Python objects, JSON-serialisable metadata, no engine imports.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Iterable, Iterator, Mapping

from .errors import GraphError


class NodeKind(str, Enum):
    """What a node represents in the story."""

    ENTRY = "entry"
    SCENE = "scene"
    CHOICE = "choice"
    CONDITION = "condition"
    ENDING = "ending"

    @property
    def is_branch(self) -> bool:
        return self in (NodeKind.CHOICE, NodeKind.CONDITION)

    @property
    def is_terminal(self) -> bool:
        return self is NodeKind.ENDING


class EdgeKind(str, Enum):
    """How one node leads to another."""

    FLOW = "flow"
    CHOICE = "choice"
    CONDITION = "condition"
    CALL = "call"
    END = "end"

    @property
    def is_primary(self) -> bool:
        """True for edges that shape the main story line.

        ``CALL`` edges are side traffic (the game returns afterwards).  They
        are drawn dashed and ignored by reachability pruning unless requested.
        """

        return self is not EdgeKind.CALL


@dataclass(slots=True)
class FlowNode:
    """A single node of the story graph."""

    id: str
    kind: NodeKind = NodeKind.SCENE
    title: str = ""
    subtitle: str = ""
    route: str = ""
    tags: tuple[str, ...] = ()
    options: tuple[tuple[str, str], ...] = ()
    """Choice options as ``(text, jump_label)``; empty for non-choice nodes."""

    meta: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.id:
            raise ValueError("FlowNode.id must not be empty")
        if not isinstance(self.kind, NodeKind):
            self.kind = NodeKind(self.kind)
        self.tags = tuple(self.tags)
        self.options = tuple((str(a), str(b)) for a, b in self.options)
        self.meta = dict(self.meta)

    # -- presentation helpers -------------------------------------------------
    def safe_title(self, fallback: str = "未命名节点") -> str:
        return self.title.strip() or self.subtitle.strip() or fallback

    def title_for(self, state: str) -> str:
        """Title shown in the flowchart for the given runtime state name.

        Locked nodes never leak their text: that is the point of a spoiler
        free chart.  Adapters call this when emitting UI code.
        """

        if state in ("locked", "ending_locked"):
            return "？？？"
        return self.safe_title()

    # -- serialisation --------------------------------------------------------
    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind.value,
            "title": self.title,
            "subtitle": self.subtitle,
            "route": self.route,
            "tags": list(self.tags),
            "options": [list(pair) for pair in self.options],
            "meta": dict(self.meta),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "FlowNode":
        return cls(
            id=str(data["id"]),
            kind=NodeKind(str(data.get("kind", NodeKind.SCENE.value))),
            title=str(data.get("title", "")),
            subtitle=str(data.get("subtitle", "")),
            route=str(data.get("route", "")),
            tags=tuple(str(t) for t in data.get("tags", ())),
            options=tuple(
                (str(pair[0]), str(pair[1]))
                for pair in data.get("options", ())
                if isinstance(pair, (list, tuple)) and len(pair) >= 2
            ),
            meta=dict(data.get("meta", {})),
        )


@dataclass(slots=True)
class FlowEdge:
    """A directed transition between two nodes."""

    source: str
    target: str
    kind: EdgeKind = EdgeKind.FLOW
    label: str = ""
    condition: str = ""
    meta: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.source or not self.target:
            raise ValueError("FlowEdge endpoints must not be empty")
        if not isinstance(self.kind, EdgeKind):
            self.kind = EdgeKind(self.kind)
        self.meta = dict(self.meta)

    @property
    def key(self) -> tuple[str, str, str, str, str]:
        return (self.source, self.target, self.kind.value, self.label, self.condition)

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "target": self.target,
            "kind": self.kind.value,
            "label": self.label,
            "condition": self.condition,
            "meta": dict(self.meta),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "FlowEdge":
        return cls(
            source=str(data["source"]),
            target=str(data["target"]),
            kind=EdgeKind(str(data.get("kind", EdgeKind.FLOW.value))),
            label=str(data.get("label", "")),
            condition=str(data.get("condition", "")),
            meta=dict(data.get("meta", {})),
        )


class FlowGraph:
    """A directed story graph with deterministic iteration order."""

    def __init__(self, entry: str | None = None) -> None:
        self.entry = entry
        self.nodes: dict[str, FlowNode] = {}
        self.edges: list[FlowEdge] = []
        self._edge_keys: set[tuple[str, str, str, str, str]] = set()

    # -- construction ---------------------------------------------------------
    def add_node(self, node: FlowNode) -> FlowNode:
        if node.id in self.nodes:
            raise GraphError(f"duplicate node id: {node.id!r}")
        self.nodes[node.id] = node
        if self.entry is None and node.kind is NodeKind.ENTRY:
            self.entry = node.id
        return node

    def ensure_node(
        self,
        node_id: str,
        kind: NodeKind = NodeKind.SCENE,
        *,
        title: str = "",
        subtitle: str = "",
        route: str = "",
        tags: Iterable[str] = (),
        meta: Mapping[str, Any] | None = None,
    ) -> FlowNode:
        """Fetch an existing node or create one.

        When the node already exists only missing presentation data is filled
        in, never overwritten.  This makes adapter passes order independent.
        """

        existing = self.nodes.get(node_id)
        if existing is not None:
            if not existing.title and title:
                existing.title = title
            if not existing.subtitle and subtitle:
                existing.subtitle = subtitle
            if not existing.route and route:
                existing.route = route
            if tags:
                existing.tags = tuple(dict.fromkeys((*existing.tags, *tags)))
            if meta:
                for key, value in meta.items():
                    existing.meta.setdefault(key, value)
            return existing
        return self.add_node(
            FlowNode(
                id=node_id,
                kind=kind,
                title=title,
                subtitle=subtitle,
                route=route,
                tags=tuple(tags),
                meta=dict(meta or {}),
            )
        )

    def connect(
        self,
        source: str,
        target: str,
        kind: EdgeKind = EdgeKind.FLOW,
        *,
        label: str = "",
        condition: str = "",
        meta: Mapping[str, Any] | None = None,
    ) -> bool:
        """Add an edge.  Returns ``False`` for duplicates and self loops."""

        if source == target:
            return False
        if source not in self.nodes:
            raise GraphError(f"edge source does not exist: {source!r}")
        if target not in self.nodes:
            raise GraphError(f"edge target does not exist: {target!r}")
        edge = FlowEdge(
            source=source,
            target=target,
            kind=kind,
            label=label,
            condition=condition,
            meta=dict(meta or {}),
        )
        if edge.key in self._edge_keys:
            return False
        self._edge_keys.add(edge.key)
        self.edges.append(edge)
        return True

    def remove_node(self, node_id: str) -> None:
        if node_id not in self.nodes:
            return
        del self.nodes[node_id]
        kept: list[FlowEdge] = []
        for edge in self.edges:
            if edge.source == node_id or edge.target == node_id:
                self._edge_keys.discard(edge.key)
            else:
                kept.append(edge)
        self.edges = kept
        if self.entry == node_id:
            self.entry = None

    def remove_edge(self, edge: FlowEdge) -> None:
        try:
            self.edges.remove(edge)
        except ValueError:
            return
        self._edge_keys.discard(edge.key)

    # -- queries --------------------------------------------------------------
    def __len__(self) -> int:
        return len(self.nodes)

    def __iter__(self) -> Iterator[FlowNode]:
        return iter(self.nodes.values())

    def get(self, node_id: str) -> FlowNode | None:
        return self.nodes.get(node_id)

    def require(self, node_id: str) -> FlowNode:
        try:
            return self.nodes[node_id]
        except KeyError as exc:  # pragma: no cover - defensive
            raise GraphError(f"unknown node: {node_id!r}") from exc

    def outgoing(self, node_id: str, *, include_calls: bool = True) -> tuple[FlowEdge, ...]:
        return tuple(
            e
            for e in self.edges
            if e.source == node_id and (include_calls or e.kind is not EdgeKind.CALL)
        )

    def incoming(self, node_id: str, *, include_calls: bool = True) -> tuple[FlowEdge, ...]:
        return tuple(
            e
            for e in self.edges
            if e.target == node_id and (include_calls or e.kind is not EdgeKind.CALL)
        )

    def successors(self, node_id: str, *, include_calls: bool = False) -> tuple[str, ...]:
        seen: dict[str, None] = {}
        for edge in self.outgoing(node_id, include_calls=include_calls):
            seen.setdefault(edge.target, None)
        return tuple(seen)

    def predecessors(self, node_id: str, *, include_calls: bool = False) -> tuple[str, ...]:
        seen: dict[str, None] = {}
        for edge in self.incoming(node_id, include_calls=include_calls):
            seen.setdefault(edge.source, None)
        return tuple(seen)

    def endings(self) -> tuple[str, ...]:
        return tuple(n.id for n in self.nodes.values() if n.kind is NodeKind.ENDING)

    def reachable(
        self,
        start: str | None = None,
        *,
        include_calls: bool = False,
    ) -> set[str]:
        start = start or self.entry
        if start is None or start not in self.nodes:
            return set()
        seen = {start}
        queue: deque[str] = deque([start])
        while queue:
            current = queue.popleft()
            for edge in self.outgoing(current, include_calls=include_calls):
                if edge.target not in seen:
                    seen.add(edge.target)
                    queue.append(edge.target)
        return seen

    def prune_unreachable(
        self,
        start: str | None = None,
        *,
        include_calls: bool = True,
        keep: Iterable[str] = (),
    ) -> tuple[str, ...]:
        """Drop nodes that no player can reach from the entry point.

        Called edges are kept by default because they are part of the chart
        even though the story continues afterwards.  Returns removed ids.
        """

        start = start or self.entry
        if start is None:
            return ()
        alive = self.reachable(start, include_calls=include_calls) | set(keep)
        dead = sorted(nid for nid in self.nodes if nid not in alive)
        for node_id in dead:
            self.remove_node(node_id)
        return tuple(dead)

    def subgraph(self, node_ids: Iterable[str]) -> "FlowGraph":
        keep = set(node_ids)
        result = FlowGraph(entry=self.entry if self.entry in keep else None)
        for node_id, node in self.nodes.items():
            if node_id in keep:
                result.add_node(
                    FlowNode(
                        id=node.id,
                        kind=node.kind,
                        title=node.title,
                        subtitle=node.subtitle,
                        route=node.route,
                        tags=node.tags,
                        options=node.options,
                        meta=dict(node.meta),
                    )
                )
        for edge in self.edges:
            if edge.source in keep and edge.target in keep:
                result.connect(
                    edge.source,
                    edge.target,
                    edge.kind,
                    label=edge.label,
                    condition=edge.condition,
                    meta=edge.meta,
                )
        if result.entry is None and result.nodes:
            result.entry = next(iter(result.nodes))
        return result

    def clone(self) -> "FlowGraph":
        return self.subgraph(self.nodes)

    # -- validation -----------------------------------------------------------
    def validate(self) -> None:
        problems: list[str] = []
        if self.nodes and self.entry is None:
            problems.append("graph has nodes but no entry point")
        if self.entry is not None and self.entry not in self.nodes:
            problems.append(f"entry point {self.entry!r} does not exist")
        for edge in self.edges:
            if edge.source not in self.nodes:
                problems.append(f"edge source missing: {edge.source!r}")
            if edge.target not in self.nodes:
                problems.append(f"edge target missing: {edge.target!r}")
            if edge.source == edge.target:
                problems.append(f"self loop: {edge.source!r}")
        if problems:
            raise GraphError("; ".join(problems))

    def assert_reachable(self) -> None:
        """Raise when a non-entry node is unreachable from the entry point."""

        if not self.nodes:
            return
        reachable = self.reachable(include_calls=True)
        missing = sorted(set(self.nodes) - reachable)
        if missing:
            raise GraphError("unreachable nodes: " + ", ".join(missing))

    # -- reporting ------------------------------------------------------------
    def stats(self) -> dict[str, Any]:
        node_counts = {kind.value: 0 for kind in NodeKind}
        for node in self.nodes.values():
            node_counts[node.kind.value] += 1
        edge_counts = {kind.value: 0 for kind in EdgeKind}
        for edge in self.edges:
            edge_counts[edge.kind.value] += 1
        return {
            "nodes": len(self.nodes),
            "edges": len(self.edges),
            "node_kinds": node_counts,
            "edge_kinds": edge_counts,
            "entry": self.entry,
            "endings": len(self.endings()),
        }

    # -- serialisation --------------------------------------------------------
    def to_dict(self) -> dict[str, Any]:
        return {
            "entry": self.entry,
            "nodes": [node.to_dict() for node in self.nodes.values()],
            "edges": [edge.to_dict() for edge in self.edges],
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "FlowGraph":
        graph = cls(entry=data.get("entry"))
        for raw in data.get("nodes", ()):
            graph.add_node(FlowNode.from_dict(raw))
        for raw in data.get("edges", ()):
            edge = FlowEdge.from_dict(raw)
            if edge.source in graph.nodes and edge.target in graph.nodes:
                graph.connect(
                    edge.source,
                    edge.target,
                    edge.kind,
                    label=edge.label,
                    condition=edge.condition,
                    meta=edge.meta,
                )
        return graph
