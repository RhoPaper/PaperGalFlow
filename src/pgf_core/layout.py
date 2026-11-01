"""Deterministic, engine independent flowchart layout.

The core exposes a small Sugiyama style pipeline:

1. break cycles (depth first back edge detection),
2. assign layers with the longest path method,
3. insert virtual nodes so long edges get their own slot,
4. reduce crossings with barycenter sweeps,
5. assign coordinates and route every edge as an orthogonal polyline.

Everything is integer based and deterministic: the same graph always produces
identical coordinates, which keeps generated game code diff friendly.
"""

from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass, field, replace
from typing import Iterable

from .errors import GraphError
from .model import EdgeKind, FlowGraph

__all__ = [
    "Point",
    "Rect",
    "RoutedEdge",
    "LayoutConfig",
    "Layout",
    "compute_layout",
]

EdgeKey = tuple[str, str, str, str]


@dataclass(frozen=True, order=True)
class Point:
    x: int
    y: int


@dataclass(frozen=True)
class Rect:
    x: int
    y: int
    w: int
    h: int

    @property
    def right(self) -> int:
        return self.x + self.w

    @property
    def bottom(self) -> int:
        return self.y + self.h

    @property
    def center_x(self) -> int:
        return self.x + self.w // 2

    @property
    def center_y(self) -> int:
        return self.y + self.h // 2

    def moved_to(self, x: int, y: int) -> "Rect":
        return replace(self, x=x, y=y)


@dataclass(frozen=True)
class RoutedEdge:
    """An edge with its polyline, ready to be drawn by an adapter."""

    source: str
    target: str
    kind: EdgeKind
    label: str
    points: tuple[Point, ...]
    back: bool = False
    label_at: Point = Point(0, 0)

    @property
    def is_primary(self) -> bool:
        return self.kind is not EdgeKind.CALL


@dataclass(frozen=True)
class LayoutConfig:
    node_width: int = 252
    node_height: int = 88
    h_gap: int = 56
    v_gap: int = 104
    margin_x: int = 88
    margin_y: int = 76
    back_channel_gap: int = 26
    label_ratio: float = 0.32

    def node_rect(self) -> Rect:
        return Rect(0, 0, self.node_width, self.node_height)


@dataclass
class Layout:
    positions: dict[str, Rect]
    edges: list[RoutedEdge]
    width: int
    height: int
    layers: tuple[tuple[str, ...], ...] = ()
    layer_of: dict[str, int] = field(default_factory=dict)

    def scaled(self, zoom: float) -> "Layout":
        """Return a zoomed copy (used by host side previews)."""

        def scale(value: float) -> int:
            return int(round(value * zoom))

        positions = {
            node_id: Rect(scale(r.x), scale(r.y), scale(r.w), scale(r.h))
            for node_id, r in self.positions.items()
        }
        edges = [
            RoutedEdge(
                source=e.source,
                target=e.target,
                kind=e.kind,
                label=e.label,
                points=tuple(Point(scale(p.x), scale(p.y)) for p in e.points),
                back=e.back,
                label_at=Point(scale(e.label_at.x), scale(e.label_at.y)),
            )
            for e in self.edges
        ]
        return Layout(
            positions=positions,
            edges=edges,
            width=scale(self.width),
            height=scale(self.height),
            layers=self.layers,
            layer_of=dict(self.layer_of),
        )


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _edge_key(source: str, target: str, kind: EdgeKind, label: str) -> EdgeKey:
    return (source, target, kind.value, label)


def _primary_edges(graph: FlowGraph) -> list[EdgeKey]:
    return [
        _edge_key(edge.source, edge.target, edge.kind, edge.label)
        for edge in graph.edges
        if edge.kind is not EdgeKind.CALL
    ]


def _break_cycles(
    node_ids: Iterable[str],
    edges: Iterable[EdgeKey],
) -> tuple[list[EdgeKey], set[EdgeKey]]:
    """Return ``(acyclic_edges, back_edges)`` using iterative DFS."""

    adjacency: dict[str, list[EdgeKey]] = defaultdict(list)
    for edge in edges:
        adjacency[edge[0]].append(edge)
    color: dict[str, int] = {}  # 1 = in stack, 2 = done
    back: set[EdgeKey] = set()
    for root in node_ids:
        if color.get(root) == 2:
            continue
        stack: list[tuple[str, int]] = [(root, 0)]
        color[root] = 1
        while stack:
            node, index = stack[-1]
            outgoing = adjacency.get(node, ())
            if index >= len(outgoing):
                color[node] = 2
                stack.pop()
                continue
            stack[-1] = (node, index + 1)
            edge = outgoing[index]
            target = edge[1]
            state = color.get(target, 0)
            if state == 0:
                color[target] = 1
                stack.append((target, 0))
            elif state == 1:
                back.add(edge)
    kept = [edge for edge in edges if edge not in back]
    return kept, back


def _assign_layers(
    node_ids: list[str],
    edges: list[EdgeKey],
) -> dict[str, int]:
    indegree = {node_id: 0 for node_id in node_ids}
    adjacency: dict[str, list[str]] = defaultdict(list)
    for source, target, _kind, _label in edges:
        adjacency[source].append(target)
        indegree[target] += 1

    layer = {node_id: 0 for node_id in node_ids}
    roots = [node_id for node_id in node_ids if indegree[node_id] == 0]
    queue: deque[str] = deque(roots)
    processed = 0
    while queue:
        current = queue.popleft()
        processed += 1
        for target in adjacency.get(current, ()):
            if layer[current] + 1 > layer[target]:
                layer[target] = layer[current] + 1
            indegree[target] -= 1
            if indegree[target] == 0:
                queue.append(target)

    if processed != len(node_ids):  # pragma: no cover - cycles already broken
        raise GraphError("cycle breaking left a cycle behind")
    return layer


def _build_virtual_nodes(
    node_ids: list[str],
    edges: list[EdgeKey],
    layer: dict[str, int],
) -> tuple[dict[int, list[str]], dict[EdgeKey, list[str]]]:
    layers: dict[int, list[str]] = defaultdict(list)
    for node_id in node_ids:
        layers[layer[node_id]].append(node_id)

    chains: dict[EdgeKey, list[str]] = {}
    for index, edge in enumerate(edges):
        source, target = edge[0], edge[1]
        start = layer[source]
        end = layer[target]
        if end - start <= 1:
            continue
        chain: list[str] = []
        for step in range(start + 1, end):
            virtual_id = f"\x00pgf-v{index}-{step}"
            chain.append(virtual_id)
            layer[virtual_id] = step
            layers[step].append(virtual_id)
        chains[edge] = chain
    return dict(layers), chains


def _ordering_adjacency(
    edges: Iterable[EdgeKey],
    chains: dict[EdgeKey, list[str]],
) -> dict[str, list[str]]:
    adjacency: dict[str, list[str]] = defaultdict(list)
    for edge in edges:
        source, target = edge[0], edge[1]
        chain = chains.get(edge)
        if chain:
            adjacency[source].append(chain[0])
            for first, second in zip(chain, chain[1:]):
                adjacency[first].append(second)
            adjacency[chain[-1]].append(target)
        else:
            adjacency[source].append(target)
    return adjacency


def _barycenter_order(
    layers: dict[int, list[str]],
    adjacency: dict[str, list[str]],
    *,
    downward: bool,
) -> None:
    keys = sorted(layers)
    if downward:
        keys = keys[1:]
    else:
        keys = list(reversed(keys[:-1]))

    for key in keys:
        reference_key = key - 1 if downward else key + 1
        reference = layers.get(reference_key, [])
        ref_index = {node_id: i for i, node_id in enumerate(reference)}
        current = layers[key]
        fallback = {node_id: i for i, node_id in enumerate(current)}

        def sort_key(node_id: str) -> tuple[float, str]:
            neighbours = adjacency.get(node_id, ())
            positions = [ref_index[n] for n in neighbours if n in ref_index]
            if not positions:
                return (float(fallback.get(node_id, 0)), node_id)
            return (sum(positions) / len(positions), node_id)

        layers[key] = sorted(current, key=sort_key)


def _crossings(layers: dict[int, list[str]], adjacency: dict[str, list[str]]) -> int:
    total = 0
    for key in sorted(layers)[:-1]:
        top = layers[key]
        bottom = layers[key + 1]
        pos_bottom = {n: i for i, n in enumerate(bottom)}
        edges = [
            (i, pos_bottom[target])
            for i, source in enumerate(top)
            for target in adjacency.get(source, ())
            if target in pos_bottom
        ]
        for i in range(len(edges)):
            for j in range(i + 1, len(edges)):
                a1, b1 = edges[i]
                a2, b2 = edges[j]
                if (a1 - a2) * (b1 - b2) < 0:
                    total += 1
    return total


# ---------------------------------------------------------------------------
# public entry point
# ---------------------------------------------------------------------------


def compute_layout(graph: FlowGraph, config: LayoutConfig | None = None) -> Layout:
    """Compute node rectangles and routed edges for ``graph``."""

    config = config or LayoutConfig()
    if not graph.nodes:
        return Layout(positions={}, edges=[], width=0, height=0)
    graph.validate()

    node_ids = list(graph.nodes)
    primary = _primary_edges(graph)
    acyclic, back_edges = _break_cycles(node_ids, primary)
    layer = _assign_layers(node_ids, acyclic)

    layers, chains = _build_virtual_nodes(node_ids, primary, layer)
    adjacency = _ordering_adjacency(primary, chains)

    best = {key: list(value) for key, value in layers.items()}
    best_score = _crossings(layers, adjacency)
    for _iteration in range(6):
        _barycenter_order(layers, adjacency, downward=True)
        _barycenter_order(layers, adjacency, downward=False)
        score = _crossings(layers, adjacency)
        if score < best_score:
            best_score = score
            best = {key: list(value) for key, value in layers.items()}
    layers = best

    # -- coordinates ---------------------------------------------------------
    max_slots = max(len(items) for items in layers.values())
    layer_width = max_slots * config.node_width + (max_slots - 1) * config.h_gap
    positions: dict[str, Rect] = {}
    virtual_points: dict[str, Point] = {}
    virtual_ids = {node_id for items in layers.values() for node_id in items if node_id.startswith("\x00")}

    for key in sorted(layers):
        items = layers[key]
        width = len(items) * config.node_width + (len(items) - 1) * config.h_gap
        start_x = config.margin_x + (layer_width - width) // 2
        y = config.margin_y + key * (config.node_height + config.v_gap)
        for index, node_id in enumerate(items):
            x = start_x + index * (config.node_width + config.h_gap)
            if node_id in virtual_ids:
                virtual_points[node_id] = Point(
                    x + config.node_width // 2, y + config.node_height // 2
                )
            else:
                positions[node_id] = Rect(x, y, config.node_width, config.node_height)

    # -- edge routing --------------------------------------------------------
    outgoing_index: dict[str, list[int]] = defaultdict(list)
    incoming_index: dict[str, list[int]] = defaultdict(list)
    for index, edge in enumerate(graph.edges):
        outgoing_index[edge.source].append(index)
        incoming_index[edge.target].append(index)

    def anchor_offset(indices: list[int], index: int, spacing: int = 34) -> int:
        if len(indices) <= 1:
            return 0
        middle = (len(indices) - 1) / 2.0
        return int(round((indices.index(index) - middle) * spacing))

    routed: list[RoutedEdge] = []
    back_channel = 0

    for index, edge in enumerate(graph.edges):
        source_rect = positions.get(edge.source)
        target_rect = positions.get(edge.target)
        if source_rect is None or target_rect is None:  # pragma: no cover - defensive
            continue

        source_layer = layer.get(edge.source, 0)
        target_layer = layer.get(edge.target, 0)
        edge_key = _edge_key(edge.source, edge.target, edge.kind, edge.label)
        is_back = (
            edge.kind is EdgeKind.CALL
            or target_layer <= source_layer
            or edge_key in back_edges
        )

        if is_back:
            channel_x = (
                config.margin_x
                + layer_width
                + config.h_gap
                + back_channel * config.back_channel_gap
            )
            back_channel += 1
            start = Point(source_rect.right, source_rect.center_y)
            end = Point(target_rect.right, target_rect.center_y)
            points = _orthogonalize(
                [start, Point(channel_x, start.y), Point(channel_x, end.y), end]
            )
            routed.append(
                RoutedEdge(
                    source=edge.source,
                    target=edge.target,
                    kind=edge.kind,
                    label=edge.label,
                    points=points,
                    back=True,
                    label_at=_point_along(points, config.label_ratio),
                )
            )
            continue

        chain = chains.get(edge_key, [])
        start = Point(
            source_rect.center_x + anchor_offset(outgoing_index[edge.source], index),
            source_rect.bottom,
        )
        end = Point(
            target_rect.center_x + anchor_offset(incoming_index[edge.target], index),
            target_rect.y,
        )
        waypoints: list[Point] = [start]
        waypoints.extend(virtual_points[virtual_id] for virtual_id in chain)
        waypoints.append(end)
        points = _orthogonalize(waypoints)
        routed.append(
            RoutedEdge(
                source=edge.source,
                target=edge.target,
                kind=edge.kind,
                label=edge.label,
                points=points,
                back=False,
                label_at=_point_along(points, config.label_ratio),
            )
        )

    width = config.margin_x
    height = config.margin_y
    for rect in positions.values():
        width = max(width, rect.right)
        height = max(height, rect.bottom)
    for edge in routed:
        width = max(width, max(point.x for point in edge.points))
        height = max(height, max(point.y for point in edge.points))
    width += config.margin_x
    height += config.margin_y

    return Layout(
        positions=positions,
        edges=routed,
        width=width,
        height=height,
        layers=tuple(tuple(items) for _key, items in sorted(layers.items())),
        layer_of={
            node_id: layer[node_id]
            for node_id in graph.nodes
            if node_id in layer
        },
    )


def _orthogonalize(points: list[Point]) -> tuple[Point, ...]:
    """Turn arbitrary waypoints into axis aligned segments."""

    cleaned: list[Point] = []
    for point in points:
        if not cleaned or cleaned[-1] != point:
            cleaned.append(point)
    if len(cleaned) <= 1:
        return tuple(cleaned)
    result: list[Point] = [cleaned[0]]
    for target in cleaned[1:]:
        source = result[-1]
        if source.x == target.x or source.y == target.y:
            result.append(target)
            continue
        mid_y = source.y + (target.y - source.y) // 2
        result.append(Point(source.x, mid_y))
        result.append(Point(target.x, mid_y))
        result.append(target)
    compact: list[Point] = []
    for point in result:
        if len(compact) >= 2 and _collinear(compact[-2], compact[-1], point):
            compact[-1] = point
        else:
            compact.append(point)
    return tuple(compact)


def _collinear(a: Point, b: Point, c: Point) -> bool:
    return (a.x == b.x == c.x) or (a.y == b.y == c.y)


def _point_along(points: tuple[Point, ...], ratio: float) -> Point:
    if not points:
        return Point(0, 0)
    total = 0.0
    lengths: list[float] = []
    for a, b in zip(points, points[1:]):
        length = abs(a.x - b.x) + abs(a.y - b.y)
        lengths.append(length)
        total += length
    if total == 0:
        return points[0]
    target = total * ratio
    walked = 0.0
    for (a, b), length in zip(zip(points, points[1:]), lengths):
        if walked + length >= target:
            if length == 0:
                return a
            offset = (target - walked) / length
            return Point(
                int(round(a.x + (b.x - a.x) * offset)),
                int(round(a.y + (b.y - a.y) * offset)),
            )
        walked += length
    return points[-1]
