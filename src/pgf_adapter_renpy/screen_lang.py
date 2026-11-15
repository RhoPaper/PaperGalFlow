"""Reconstruct readable screen language from a compiled ``.rpyc`` screen.

Ren'Py does not keep the original screen source in a compiled script: only an
SL2 object tree.  This module renders that tree back to a conservative subset
of screen language, which is enough to copy a ``quick_menu`` into a wrapper
and append PaperGalFlow's own button for games that ship no ``.rpy`` files.

The decompiler is deliberately strict.  When a node cannot be represented
faithfully (ATL transforms, unknown positional layouts, malformed branches) it
reports ``supported = False`` and the caller keeps the non-invasive overlay
fallback instead of writing a screen with missing behaviour.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Iterable

from .script_model import ScreenElement, ScreenInfo

__all__ = ["ScreenDecompileResult", "decompile_screen", "render_screen"]

_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_PROPERTY_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_MAX_DEPTH = 32
_MAX_ELEMENTS = 2000

#: Preview/displayable statements that can be emitted with positional args and
#: a block.  Anything else is rejected unless it is a plain identifier with no
#: children (some user defined displayables are valid that way).
_SIMPLE_KINDS = {
    "text",
    "textbutton",
    "imagebutton",
    "button",
    "frame",
    "window",
    "vbox",
    "hbox",
    "fixed",
    "grid",
    "vpgrid",
    "viewport",
    "side",
    "bar",
    "null",
    "timer",
    "key",
    "add",
    "image",
    "label",
}
_REJECTED_KINDS = {"atl", "transform", "showif"}


@dataclass
class ScreenDecompileResult:
    name: str
    source: str = ""
    supported: bool = False
    warnings: list[str] = field(default_factory=list)
    properties: dict[str, str] = field(default_factory=dict)
    parameters: str = ""
    element_count: int = 0

    def screen_source(self) -> str:
        """Return a complete ``screen`` definition (body plus header)."""

        if not self.supported:
            return ""
        header = f"screen {self.name}{self.parameters or '()'}:"
        body = self.source.rstrip("\n")
        return header + ("\n" + body if body else "") + "\n"


class _Unsupported(Exception):
    pass


def _indent(level: int) -> str:
    return "    " * level


def _check_kind(kind: str) -> str:
    if not kind or not _IDENTIFIER_RE.match(kind):
        raise _Unsupported(f"invalid screen statement {kind!r}")
    return kind


def _render_properties(properties: dict[str, str], level: int) -> list[str]:
    lines: list[str] = []
    for key, value in properties.items():
        if not _PROPERTY_RE.match(str(key)):
            raise _Unsupported(f"invalid screen property {key!r}")
        text = str(value).strip()
        if not text:
            continue
        lines.append(f"{_indent(level)}{key} {text}")
    return lines


def _render_children(children: Iterable[ScreenElement], level: int, depth: int) -> list[str]:
    lines: list[str] = []
    for child in children:
        lines.extend(_render_element(child, level, depth + 1))
    return lines


def _render_if(element: ScreenElement, level: int, depth: int) -> list[str]:
    branches = element.branches
    if not branches:
        # Older compiled trees do not preserve branch boundaries.  Group the
        # flattened children by their condition, which is exactly how they
        # appear in SLIf entries.
        grouped: list[tuple[str, list[ScreenElement]]] = []
        for child in element.children:
            condition = child.condition or ""
            if grouped and grouped[-1][0] == condition:
                grouped[-1][1].append(child)
            else:
                grouped.append((condition, [child]))
        branches = grouped
    if not branches:
        raise _Unsupported("empty if statement")

    lines: list[str] = []
    for index, (condition, children) in enumerate(branches):
        condition = str(condition or "").strip()
        if index == 0:
            if not condition:
                raise _Unsupported("if statement without a condition")
            keyword = "if"
        elif condition:
            keyword = "elif"
        else:
            keyword = "else"
        if keyword != "else":
            lines.append(f"{_indent(level)}{keyword} {condition}:")
        else:
            lines.append(f"{_indent(level)}else:")
        body = _render_children(children, level + 1, depth + 1)
        if not body:
            body = [f"{_indent(level + 1)}pass"]
        lines.extend(body)
    return lines


def _render_for(element: ScreenElement, level: int, depth: int) -> list[str]:
    expression = element.for_expression.strip()
    variable = element.for_variable.strip()
    index = element.for_index.strip()
    if not expression or not variable:
        raise _Unsupported("for statement without variable/expression")
    names = f"{index}, {variable}" if index else variable
    lines = [f"{_indent(level)}for {names} in {expression}:"]
    body = _render_children(element.children, level + 1, depth + 1)
    lines.extend(body or [f"{_indent(level + 1)}pass"])
    return lines


def _render_element(element: ScreenElement, level: int, depth: int) -> list[str]:
    if depth > _MAX_DEPTH:
        raise _Unsupported("screen nesting is too deep")
    kind = str(element.kind or "").strip()
    if kind == "block":
        return _render_children(element.children, level, depth)
    if kind == "if":
        return _render_if(element, level, depth)
    if kind == "for":
        return _render_for(element, level, depth)
    if kind == "use":
        target = element.target.strip()
        if not target or not _IDENTIFIER_RE.match(target.split("(")[0].strip()):
            raise _Unsupported(f"invalid use target {target!r}")
        line = f"{_indent(level)}use {target}"
        properties = _render_properties(element.properties, level + 1)
        if properties:
            line += ":"
            return [line] + properties + _render_children(element.children, level + 1, depth + 1)
        if element.children:
            raise _Unsupported("use statement with children")
        return [line]
    if kind in _REJECTED_KINDS:
        raise _Unsupported(f"screen statement {kind!r} cannot be reconstructed")

    _check_kind(kind)
    positionals = [str(value).strip() for value in element.positionals if str(value).strip()]
    if not positionals and element.text.strip():
        positionals = [element.text.strip()]
    if kind in {"text", "textbutton", "label"} and not positionals:
        raise _Unsupported(f"{kind} statement without text")
    if kind in {"add", "image"} and not positionals:
        raise _Unsupported(f"{kind} statement without an image expression")
    if kind in {"key", "timer", "grid", "vpgrid", "bar"} and not positionals:
        raise _Unsupported(f"{kind} statement without positional arguments")

    line = f"{_indent(level)}{kind}"
    if positionals:
        line += " " + " ".join(positionals)
    properties = _render_properties(element.properties, level + 1)
    children = _render_children(element.children, level + 1, depth + 1)
    if properties or children:
        line += ":"
        return [line] + properties + children
    return [line]


def decompile_screen(screen: ScreenInfo) -> ScreenDecompileResult:
    """Render one compiled screen's body, or report why it is unsafe."""

    result = ScreenDecompileResult(
        name=screen.name,
        properties=dict(screen.properties),
        parameters=screen.parameters or "",
        element_count=sum(1 for _element in screen.walk()),
    )
    if not screen.name:
        result.warnings.append("screen has no name")
        return result
    if result.element_count > _MAX_ELEMENTS:
        result.warnings.append(f"screen has too many elements ({result.element_count})")
        return result
    try:
        lines = _render_properties(screen.properties, 1)
        lines.extend(_render_children(screen.elements, 1, 0))
    except _Unsupported as exc:
        result.warnings.append(str(exc))
        return result
    if not lines:
        result.warnings.append("screen body is empty")
        return result
    result.source = "\n".join(lines).rstrip() + "\n"
    result.supported = True
    return result


def render_screen(screen: ScreenInfo) -> ScreenDecompileResult:
    """Compatibility alias returning a full screen definition on success."""

    result = decompile_screen(screen)
    if result.supported:
        result.source = result.screen_source()
    return result
