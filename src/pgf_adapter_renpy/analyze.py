"""Turn normalized Ren'Py scripts into a :class:`~pgf_core.model.FlowGraph`.

The analysis walks each label like the Ren'Py interpreter would: linear
statements advance the current node, menus and ``if`` chains become decision
nodes with labelled outgoing edges, jumps terminate a path, calls become side
edges and returns become ending nodes.  Fall through is tracked explicitly so
that branches which converge on a later jump share one merge node instead of
being silently dropped.

The result is engine independent; only the node metadata (``label``) remembers
where a click should send the player.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Iterable, Iterator

from pgf_core.errors import GraphError
from pgf_core.model import EdgeKind, FlowGraph, NodeKind

from .script_model import ScriptFile, Statement, Stmt

__all__ = ["AnalyzeOptions", "AnalyzeResult", "build_graph"]

_TRANSLATE_TYPES = {"translate", "Translate", "TranslateBlock", "TranslatePython"}
_TEXT_TAG_RE = re.compile(r"\{[^{}]*\}")
_WHITESPACE_RE = re.compile(r"\s+")


# ---------------------------------------------------------------------------
# public options / result
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AnalyzeOptions:
    entry_label: str = "start"
    include_call_edges: bool = True
    include_side_labels: bool = False
    collapse_routers: bool = True
    merge_trivial_conditions: bool = True
    title_chars: int = 42
    skip_labels: tuple[str, ...] = ()
    #: Ren'Py engine labels that mean "the story stopped here".  They are not
    #: charted as scenes: a jump to them becomes an ending node with this title.
    special_endings: tuple[tuple[str, str], ...] = (
        ("splashscreen", "返回标题画面"),
        ("quit", "退出游戏"),
        ("main_menu", "返回主菜单"),
    )

    def cleaned(self) -> "AnalyzeOptions":
        return AnalyzeOptions(
            entry_label=self.entry_label.strip() or "start",
            include_call_edges=self.include_call_edges,
            include_side_labels=self.include_side_labels,
            collapse_routers=self.collapse_routers,
            merge_trivial_conditions=self.merge_trivial_conditions,
            title_chars=max(8, int(self.title_chars)),
            skip_labels=tuple(self.skip_labels),
            special_endings=tuple(self.special_endings),
        )


@dataclass
class AnalyzeResult:
    graph: FlowGraph
    warnings: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    entry_label: str = ""
    label_count: int = 0
    script_count: int = 0

    @property
    def ok(self) -> bool:
        return bool(self.graph.nodes) and not self.warnings

    def summary(self) -> dict[str, object]:
        return {
            "entry": self.entry_label,
            "labels": self.label_count,
            "scripts": self.script_count,
            "warnings": len(self.warnings),
            "graph": self.graph.stats(),
        }


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def clean_text(text: str, limit: int = 42) -> str:
    """Make dialogue text suitable for a flowchart label."""

    if not text:
        return ""
    text = _TEXT_TAG_RE.sub("", str(text))
    text = text.replace("\\n", " ").replace("\n", " ")
    text = _WHITESPACE_RE.sub(" ", text).strip()
    text = text.strip("\"'“”")
    if limit > 0 and len(text) > limit:
        text = text[: max(1, limit - 1)].rstrip() + "…"
    return text


def _iter_statements(statements: Iterable[Statement]) -> Iterator[Statement]:
    for statement in statements:
        if statement.meta.get("renpy_type") in _TRANSLATE_TYPES:
            continue
        yield statement
        for block in statement.iter_blocks():
            yield from _iter_statements(block)


def _first_says(statements: Iterable[Statement], limit: int = 2) -> tuple[str, ...]:
    """Return the first few spoken lines, used to find the history checkpoint."""

    found: list[str] = []

    def walk(block: Iterable[Statement]) -> bool:
        for statement in block:
            if statement.meta.get("renpy_type") in _TRANSLATE_TYPES:
                continue
            if statement.kind == Stmt.SAY and statement.text.strip():
                found.append(statement.text)
                if len(found) >= limit:
                    return True
            for nested in statement.iter_blocks():
                if walk(nested):
                    return True
        return False

    walk(statements)
    return tuple(found)


def _first_say(statements: Iterable[Statement]) -> str:
    found = _first_says(statements, 1)
    return found[0] if found else ""


def _last_say(statements: Iterable[Statement]) -> str:
    last = ""
    for statement in statements:
        if statement.meta.get("renpy_type") in _TRANSLATE_TYPES:
            continue
        if statement.kind == Stmt.SAY and statement.text.strip():
            last = statement.text
        for block in statement.iter_blocks():
            nested = _last_say(block)
            if nested:
                last = nested
    return last


def _has_say(statements: Iterable[Statement]) -> bool:
    return any(s.kind == Stmt.SAY and s.text.strip() for s in _iter_statements(statements))


def _has_menu(statements: Iterable[Statement]) -> bool:
    return any(s.kind == Stmt.MENU for s in _iter_statements(statements))


@dataclass
class _LabelDef:
    name: str
    statement: Statement
    script: ScriptFile
    script_index: int
    block: list[Statement] = field(default_factory=list)
    first_say: str = ""
    first_says: tuple[str, ...] = ()
    last_say: str = ""
    has_dialogue: bool = False
    has_menu: bool = False


# ---------------------------------------------------------------------------
# join points
# ---------------------------------------------------------------------------


class _Join:
    """A point where control continues after a branch.

    Edges arriving while the join has no node are buffered; when the rest of
    the sequence turns out to start with a decision node the buffer is flushed
    into that node, otherwise it is delegated to the enclosing join.  This is
    what lets ``menu`` options converge without inventing a node per option.
    """

    def __init__(self, builder: "_GraphBuilder") -> None:
        self.builder = builder
        self.node: str | None = None
        self.exits: tuple[str, ...] | None = None
        self.delegate: "_Join | None" = None
        self.pending: list[tuple[str, EdgeKind, str]] = []

    @property
    def settled(self) -> bool:
        return self.node is not None or self.exits is not None

    @property
    def has_pending(self) -> bool:
        if self.pending:
            return True
        return bool(self.delegate is not None and self.delegate.has_pending)

    def incoming(self, source: str, kind: EdgeKind, label: str) -> None:
        if self.node is not None:
            self.builder.connect(source, self.node, kind, label)
        elif self.exits is not None:
            for target in self.exits:
                self.builder.connect(source, target, kind, label)
        elif self.delegate is not None:
            self.delegate.incoming(source, kind, label)
        else:
            self.pending.append((source, kind, label))

    def bind_node(self, node_id: str) -> None:
        if self.settled:
            return
        self.node = node_id
        self.delegate = None
        for source, kind, label in self.pending:
            self.builder.connect(source, node_id, kind, label)
        self.pending.clear()

    def bind_exits(self, targets: Iterable[str]) -> None:
        if self.settled:
            return
        self.exits = tuple(dict.fromkeys(targets))
        self.delegate = None
        for source, kind, label in self.pending:
            for target in self.exits:
                self.builder.connect(source, target, kind, label)
        self.pending.clear()

    def bind_join(self, other: "_Join") -> None:
        if self.settled:
            return
        if other is self:
            return
        self.delegate = other
        for source, kind, label in self.pending:
            other.incoming(source, kind, label)
        self.pending.clear()


# ---------------------------------------------------------------------------
# builder
# ---------------------------------------------------------------------------


class _GraphBuilder:
    def __init__(self, scripts: Iterable[ScriptFile], options: AnalyzeOptions) -> None:
        self.scripts = tuple(scripts)
        self.options = options.cleaned()
        self.graph = FlowGraph()
        self.warnings: list[str] = []
        self.notes: list[str] = []
        self.labels: dict[str, _LabelDef] = {}
        self.label_nodes: dict[str, str] = {}
        self.ending_nodes: dict[tuple[str, int], str] = {}
        self.used_ids: set[str] = set()
        self.dropped_ids: set[str] = set()
        self.next_label: dict[str, str] = {}
        self.entry_label = ""
        self.special_endings = dict(self.options.special_endings)
        self.special_nodes: dict[str, str] = {}

    # -- setup ---------------------------------------------------------------
    def build(self) -> AnalyzeResult:
        self._collect_labels()
        if not self.labels:
            self.warnings.append("no story labels were found in the game scripts")
            return self._result()

        self.entry_label = self._pick_entry()
        self._build_next_label_map()
        self._create_label_nodes()
        self.graph.entry = self.label_nodes[self.entry_label]
        for name in self._label_order():
            self._analyze_label(name)
        if self.options.collapse_routers:
            self._collapse_routers()
        if self.options.merge_trivial_conditions:
            self._merge_trivial_conditions()
        self._prune()
        self._promote_entry()
        self.notes = [
            note
            for note in self.notes
            if not any(f"'{node_id}'" in note for node_id in self.dropped_ids)
        ]
        try:
            self.graph.validate()
        except GraphError as exc:
            self.warnings.append(f"graph validation failed: {exc}")
        return self._result()

    def _result(self) -> AnalyzeResult:
        return AnalyzeResult(
            graph=self.graph,
            warnings=self.warnings,
            notes=self.notes,
            entry_label=self.entry_label,
            label_count=len(self.labels),
            script_count=len(self.scripts),
        )

    def _collect_labels(self) -> None:
        for script_index, script in enumerate(self.scripts):
            for statement in _iter_statements(script.statements):
                if statement.kind != Stmt.LABEL or not statement.name:
                    continue
                name = statement.name
                if name.startswith("_"):
                    continue
                if name in self.options.skip_labels:
                    continue
                if name in self.special_endings:
                    continue
                if name in self.labels:
                    self.warnings.append(
                        f"duplicate label {name!r} at {statement.filename}:{statement.line}; keeping the first one"
                    )
                    continue
                self.labels[name] = _LabelDef(
                    name=name,
                    statement=statement,
                    script=script,
                    script_index=script_index,
                    block=statement.block,
                    first_say=_first_say(statement.block),
                    first_says=_first_says(statement.block, 2),
                    last_say=_last_say(statement.block),
                    has_dialogue=_has_say(statement.block),
                    has_menu=_has_menu(statement.block),
                )

    def _pick_entry(self) -> str:
        if self.options.entry_label in self.labels:
            return self.options.entry_label
        if "start" in self.labels:
            self.notes.append(
                f"entry label {self.options.entry_label!r} not found; falling back to 'start'"
            )
            return "start"
        first = next(iter(self.labels))
        self.warnings.append(
            f"entry label {self.options.entry_label!r} not found; using {first!r}"
        )
        return first

    def _label_order(self) -> list[str]:
        return sorted(
            self.labels,
            key=lambda name: (self.labels[name].script_index, self.labels[name].statement.line, name),
        )

    def _build_next_label_map(self) -> None:
        by_script: dict[int, list[_LabelDef]] = {}
        for definition in self.labels.values():
            by_script.setdefault(definition.script_index, []).append(definition)
        for definitions in by_script.values():
            definitions.sort(key=lambda item: (item.statement.line, item.name))
            for current, following in zip(definitions, definitions[1:]):
                self.next_label[current.name] = following.name

    def _create_label_nodes(self) -> None:
        for name in self._label_order():
            definition = self.labels[name]
            node_id = name
            title = clean_text(definition.first_say, self.options.title_chars)
            self.graph.ensure_node(
                node_id,
                NodeKind.SCENE,
                title=title,
                subtitle=name,
                meta={
                    "label": name,
                    "file": definition.statement.filename,
                    "line": str(definition.statement.line),
                    "history_text": clean_text(definition.first_says[0], 0)
                    if definition.first_says
                    else "",
                    "history_text2": clean_text(definition.first_says[1], 0)
                    if len(definition.first_says) > 1
                    else "",
                },
            )
            self.label_nodes[name] = node_id
            self.used_ids.add(node_id)

    # -- node creation -------------------------------------------------------
    def _unique_id(self, base: str) -> str:
        if base not in self.used_ids:
            self.used_ids.add(base)
            return base
        counter = 2
        while f"{base}#{counter}" in self.used_ids:
            counter += 1
        result = f"{base}#{counter}"
        self.used_ids.add(result)
        return result

    def _decision_node(
        self,
        scope: str,
        line: int,
        kind: NodeKind,
        title: str,
        subtitle: str = "",
        suffix: str = "branch",
        history_text: str = "",
        history_text2: str = "",
        history_fallback: str = "",
    ) -> str:
        node_id = self._unique_id(f"{scope}::{suffix}{line}")
        self.graph.ensure_node(
            node_id,
            kind,
            title=title,
            subtitle=subtitle or scope,
            meta={
                "label": scope,
                "line": str(line),
                "history_text": history_text,
                "history_text2": history_text2,
                "history_fallback": history_fallback,
            },
        )
        return node_id

    def _ending_node(self, scope: str, line: int, text: str, fallthrough: bool = False) -> str:
        key = (scope, 0 if fallthrough else line)
        existing = self.ending_nodes.get(key)
        if existing is not None and existing in self.graph.nodes:
            return existing
        node_id = self._unique_id(f"{scope}::end" + ("" if fallthrough else str(line)))
        title = clean_text(text, self.options.title_chars)
        if not title:
            title = f"结局 · {scope}"
        self.graph.ensure_node(
            node_id,
            NodeKind.ENDING,
            title=title,
            subtitle=scope,
            meta={
                "label": scope,
                "line": str(line),
                "fallthrough": "1" if fallthrough else "",
                "history_text": clean_text(text, 0),
            },
        )
        self.ending_nodes[key] = node_id
        return node_id

    def _special_ending(self, name: str) -> str:
        existing = self.special_nodes.get(name)
        if existing is not None and existing in self.graph.nodes:
            return existing
        node_id = self._unique_id(f"special::{name}")
        title = self.special_endings.get(name, f"结局 · {name}")
        self.graph.ensure_node(
            node_id,
            NodeKind.ENDING,
            title=title,
            subtitle=name,
            meta={"label": "", "special": name},
        )
        self.special_nodes[name] = node_id
        return node_id

    def connect(self, source: str, target: str, kind: EdgeKind, label: str = "") -> None:
        if source not in self.graph.nodes or target not in self.graph.nodes:
            return
        self.graph.connect(source, target, kind, label=label)

    # -- flow analysis -------------------------------------------------------
    def _analyze_label(self, name: str) -> None:
        definition = self.labels[name]
        node_id = self.label_nodes[name]
        join = _Join(self)
        self._analyze_seq(definition.block, node_id, join, EdgeKind.FLOW, "", name)

        if not join.has_pending:
            return
        following = self.next_label.get(name)
        if following and following in self.label_nodes:
            join.bind_node(self.label_nodes[following])
            self.notes.append(f"label {name!r} falls through to {following!r}")
        else:
            ending = self._ending_node(name, 0, definition.last_say, fallthrough=True)
            join.bind_node(ending)
            self.notes.append(f"label {name!r} falls off the end of the script")

    def _analyze_seq(
        self,
        statements: list[Statement],
        anchor: str | None,
        join: _Join,
        edge_kind: EdgeKind,
        edge_label: str,
        scope: str,
    ) -> None:
        pending_joins: list[_Join] = []
        pending_kind = edge_kind
        pending_label = edge_label
        last_say = ""

        def attach(node_id: str) -> None:
            nonlocal pending_kind, pending_label
            if anchor is not None:
                self.connect(anchor, node_id, pending_kind, pending_label)
            else:
                for pending in pending_joins:
                    pending.bind_node(node_id)
                pending_joins.clear()
            pending_kind, pending_label = EdgeKind.FLOW, ""

        for statement in statements:
            kind = statement.kind
            if kind == Stmt.SAY:
                if statement.text.strip():
                    last_say = statement.text
                continue
            if kind in (Stmt.PYTHON, Stmt.DEFINE, Stmt.STYLE, Stmt.SCREEN, Stmt.INIT, Stmt.PASS):
                continue
            if kind == Stmt.LABEL:
                continue
            if kind == Stmt.MENU:
                if not statement.items:
                    continue
                caption = clean_text(statement.meta.get("caption", ""), 0)
                previous_line = clean_text(last_say, 0)
                node_id = self._decision_node(
                    scope,
                    statement.line,
                    NodeKind.CHOICE,
                    clean_text(statement.meta.get("caption", ""), self.options.title_chars) or "选项",
                    scope,
                    "menu",
                    history_text=caption or previous_line,
                    history_fallback=previous_line if caption and previous_line != caption else "",
                )
                attach(node_id)
                rest = _Join(self)
                for item in statement.items:
                    self._analyze_seq(
                        item.block,
                        node_id,
                        rest,
                        EdgeKind.CHOICE,
                        clean_text(item.text, 0),
                        scope,
                    )
                anchor = None
                pending_joins = [rest]
                pending_kind, pending_label = EdgeKind.FLOW, ""
                continue
            if kind == Stmt.IF:
                if not statement.entries:
                    continue
                node_id = self._decision_node(
                    scope,
                    statement.line,
                    NodeKind.CONDITION,
                    "条件分歧",
                    scope,
                    "if",
                )
                attach(node_id)
                rest = _Join(self)
                for entry in statement.entries:
                    condition = entry.condition.strip()
                    label = "否则" if condition in ("", "True") else clean_text(condition, 0)
                    self._analyze_seq(
                        entry.block,
                        node_id,
                        rest,
                        EdgeKind.CONDITION,
                        label,
                        scope,
                    )
                anchor = None
                pending_joins = [rest]
                pending_kind, pending_label = EdgeKind.FLOW, ""
                continue
            if kind == Stmt.JUMP:
                target = statement.target
                target_node = self.label_nodes.get(target)
                if target_node is None and target in self.special_endings:
                    target_node = self._special_ending(target)
                if target_node is None:
                    if not target.startswith("_"):
                        self.warnings.append(
                            f"jump target {target!r} not found at {statement.filename}:{statement.line}"
                        )
                    pending_kind, pending_label = EdgeKind.FLOW, ""
                    return
                if anchor is not None:
                    self.connect(anchor, target_node, pending_kind, pending_label)
                else:
                    for pending in pending_joins:
                        pending.bind_node(target_node)
                    pending_joins.clear()
                pending_kind, pending_label = EdgeKind.FLOW, ""
                return
            if kind == Stmt.CALL:
                target = statement.target
                target_node = self.label_nodes.get(target)
                if target_node is None:
                    if target and target not in self.special_endings and not target.startswith("_"):
                        self.notes.append(
                            f"call target {target!r} not found at {statement.filename}:{statement.line}"
                        )
                    pending_kind, pending_label = EdgeKind.FLOW, ""
                    continue
                # A call is a side trip: the chart continues afterwards.  When
                # the call is reached through a still open branch join we skip
                # the side edge rather than inventing a merge node just to own
                # it; the join itself stays open for the following statement.
                if anchor is not None and self.options.include_call_edges:
                    self.connect(anchor, target_node, EdgeKind.CALL)
                pending_kind, pending_label = EdgeKind.FLOW, ""
                continue
            if kind == Stmt.RETURN:
                ending = self._ending_node(scope, statement.line, last_say)
                if anchor is not None:
                    self.connect(
                        anchor,
                        ending,
                        EdgeKind.END,
                        pending_label if pending_label else "",
                    )
                else:
                    for pending in pending_joins:
                        pending.bind_node(ending)
                    pending_joins.clear()
                pending_kind, pending_label = EdgeKind.FLOW, ""
                return
            # OTHER statements with blocks (while, for, ...) are opaque: their
            # nested jumps are not part of the chart.
        if pending_joins:
            for pending in pending_joins:
                pending.bind_join(join)
        elif anchor is not None:
            join.incoming(anchor, pending_kind, pending_label)

    # -- post processing -----------------------------------------------------
    def _collapse_routers(self) -> None:
        changed = True
        while changed:
            changed = False
            for node_id in list(self.graph.nodes):
                node = self.graph.nodes.get(node_id)
                if node is None or node.kind is not NodeKind.SCENE:
                    continue
                if node.title.strip() or node.meta.get("merge"):
                    continue
                outgoing = [
                    edge
                    for edge in self.graph.edges
                    if edge.source == node_id and edge.kind is not EdgeKind.CALL
                ]
                if len(outgoing) != 1:
                    continue
                if any(edge.kind is EdgeKind.CALL for edge in self.graph.edges if edge.source == node_id):
                    continue
                if any(edge.kind is EdgeKind.CALL for edge in self.graph.edges if edge.target == node_id):
                    continue
                target = outgoing[0].target
                if target == node_id or target not in self.graph.nodes:
                    continue
                if self.graph.nodes[target].kind is NodeKind.ENDING:
                    # Still collapse: a router that only leads to an ending is
                    # not worth its own node, but keep the entry flag.
                    pass
                incoming = [edge for edge in self.graph.edges if edge.target == node_id]
                for edge in incoming:
                    self.graph.connect(
                        edge.source,
                        target,
                        edge.kind,
                        label=edge.label,
                        condition=edge.condition,
                    )
                was_entry = self.graph.entry == node_id
                self.graph.remove_node(node_id)
                self.used_ids.discard(node_id)
                self.dropped_ids.add(node_id)
                if was_entry:
                    self.graph.entry = target
                self.notes.append(f"collapsed router label {node_id!r}")
                changed = True

    def _merge_trivial_conditions(self) -> None:
        changed = True
        while changed:
            changed = False
            for node_id in list(self.graph.nodes):
                node = self.graph.nodes.get(node_id)
                if node is None or node.kind is not NodeKind.CONDITION:
                    continue
                outgoing = [edge for edge in self.graph.edges if edge.source == node_id]
                if not outgoing:
                    continue
                if any(edge.kind is EdgeKind.CALL for edge in outgoing):
                    continue
                targets = {edge.target for edge in outgoing}
                if len(targets) != 1:
                    continue
                target = next(iter(targets))
                if target == node_id or target not in self.graph.nodes:
                    continue
                incoming = [edge for edge in self.graph.edges if edge.target == node_id]
                for edge in incoming:
                    self.graph.connect(
                        edge.source,
                        target,
                        edge.kind,
                        label=edge.label,
                        condition=edge.condition,
                    )
                was_entry = self.graph.entry == node_id
                self.graph.remove_node(node_id)
                self.used_ids.discard(node_id)
                self.dropped_ids.add(node_id)
                if was_entry:
                    self.graph.entry = target
                changed = True

    def _prune(self) -> None:
        if not self.graph.nodes:
            return
        if self.graph.entry is None or self.graph.entry not in self.graph.nodes:
            self.graph.entry = next(iter(self.graph.nodes))
        removed = self.graph.prune_unreachable(include_calls=self.options.include_side_labels)
        if removed:
            removed_set = set(removed)
            self.dropped_ids.update(removed_set)
            self.notes = [
                note
                for note in self.notes
                if not any(f"'{node_id}'" in note for node_id in removed_set)
            ]
            self.notes.append(f"pruned {len(removed)} unreachable node(s)")
        # Call edges that point at pruned labels were dropped with their
        # nodes; nothing else to do.

    def _promote_entry(self) -> None:
        if not self.graph.nodes:
            return
        entry = self.graph.entry
        if entry is None or entry not in self.graph.nodes:
            entry = next(iter(self.graph.nodes))
            self.graph.entry = entry
        node = self.graph.nodes[entry]
        if node.kind is not NodeKind.ENDING:
            node.kind = NodeKind.ENTRY


# ---------------------------------------------------------------------------
# public API
# ---------------------------------------------------------------------------


def build_graph(
    scripts: Iterable[ScriptFile],
    options: AnalyzeOptions | None = None,
) -> AnalyzeResult:
    """Build a story graph from parsed scripts."""

    return _GraphBuilder(scripts, options or AnalyzeOptions()).build()
