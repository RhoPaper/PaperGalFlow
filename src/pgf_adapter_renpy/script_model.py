"""Engine specific but parser independent script representation.

Both the ``.rpy`` text parser and the ``.rpyc`` compiled AST reader normalise
into these structures.  Everything above this layer (flow analysis, style
probing, entry hooks, code generation) is source format agnostic.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Iterator


class Stmt:
    """String constants for :attr:`Statement.kind`."""

    LABEL = "label"
    SAY = "say"
    MENU = "menu"
    IF = "if"
    JUMP = "jump"
    CALL = "call"
    RETURN = "return"
    PYTHON = "python"
    DEFINE = "define"
    STYLE = "style"
    SCREEN = "screen"
    INIT = "init"
    PASS = "pass"
    OTHER = "other"


@dataclass
class ScreenElement:
    """A node of a (compiled) Ren'Py screen language tree."""

    kind: str
    line: int = 0
    properties: dict[str, str] = field(default_factory=dict)
    children: list["ScreenElement"] = field(default_factory=list)
    text: str = ""
    target: str = ""
    condition: str = ""

    def walk(self) -> Iterator["ScreenElement"]:
        yield self
        for child in self.children:
            yield from child.walk()

    def prop(self, name: str, default: str = "") -> str:
        return self.properties.get(name, default)

    def has_prop(self, name: str) -> bool:
        return name in self.properties

    def summary(self) -> str:
        properties = ", ".join(f"{key}={value}" for key, value in self.properties.items())
        return f"{self.kind}({properties})"


@dataclass
class ScreenInfo:
    name: str
    line: int = 0
    parameters: str = ""
    properties: dict[str, str] = field(default_factory=dict)
    elements: list[ScreenElement] = field(default_factory=list)
    source: str = ""
    use_of: tuple[str, ...] = ()

    def walk(self) -> Iterator[ScreenElement]:
        for element in self.elements:
            yield from element.walk()

    def uses(self, screen_name: str) -> bool:
        if screen_name in self.use_of:
            return True
        return any(
            element.kind == "use" and element.target == screen_name
            for element in self.walk()
        )


@dataclass
class MenuItem:
    text: str
    condition: str = ""
    block: list["Statement"] = field(default_factory=list)
    line: int = 0


@dataclass
class IfEntry:
    condition: str
    block: list["Statement"] = field(default_factory=list)


@dataclass
class Statement:
    kind: str
    line: int = 0
    filename: str = ""
    name: str = ""
    text: str = ""
    who: str = ""
    target: str = ""
    source: str = ""
    condition: str = ""
    items: list[MenuItem] = field(default_factory=list)
    entries: list[IfEntry] = field(default_factory=list)
    block: list["Statement"] = field(default_factory=list)
    meta: dict[str, str] = field(default_factory=dict)

    # -- convenience ---------------------------------------------------------
    def iter_blocks(self) -> Iterator[list["Statement"]]:
        if self.block:
            yield self.block
        for item in self.items:
            if item.block:
                yield item.block
        for entry in self.entries:
            if entry.block:
                yield entry.block

    def walk(self) -> Iterator["Statement"]:
        yield self
        for block in self.iter_blocks():
            for statement in block:
                yield from statement.walk()

    @property
    def is_flow(self) -> bool:
        return self.kind in (
            Stmt.LABEL,
            Stmt.SAY,
            Stmt.MENU,
            Stmt.IF,
            Stmt.JUMP,
            Stmt.CALL,
            Stmt.RETURN,
        )


@dataclass
class ScriptFile:
    filename: str
    statements: list[Statement] = field(default_factory=list)
    source_format: str = "rpyc"
    source_text: str = ""
    metadata: dict[str, object] = field(default_factory=dict)

    def labels(self) -> dict[str, Statement]:
        result: dict[str, Statement] = {}
        for statement in self.statements:
            for node in statement.walk():
                if node.kind == Stmt.LABEL and node.name:
                    result.setdefault(node.name, node)
        return result

    def screens(self) -> dict[str, ScreenInfo]:
        result: dict[str, ScreenInfo] = {}
        for statement in self.statements:
            for node in statement.walk():
                if node.kind == Stmt.SCREEN:
                    info = node.meta.get("screen")
                    if isinstance(info, ScreenInfo):
                        result.setdefault(info.name, info)
        return result

    def defines(self) -> dict[str, str]:
        result: dict[str, str] = {}
        for statement in self.statements:
            for node in statement.walk():
                if node.kind == Stmt.DEFINE and node.name:
                    result[node.name] = node.source
        return result

    def styles(self) -> dict[str, dict[str, str]]:
        result: dict[str, dict[str, str]] = {}
        for statement in self.statements:
            for node in statement.walk():
                if node.kind == Stmt.STYLE and node.name:
                    result.setdefault(node.name, {}).update(node.meta.get("properties", {}))
        return result


def flatten(statements: Iterable[Statement]) -> Iterator[Statement]:
    for statement in statements:
        yield from statement.walk()
