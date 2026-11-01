"""A small, dependency free parser for Ren'Py ``.rpy`` source files.

This is not a full Ren'Py implementation.  It parses the subset that matters
for building a story graph and for patching UI:

* labels (including local ``.labels``), dialogue, menus and their conditions,
  ``if``/``elif``/``else`` chains, jumps, calls, returns,
* ``define``/``default``, style blocks, ``python`` blocks and ``screen``
  definitions (kept as source plus a light element tree).

When the parser meets something it does not understand it degrades to an
``other`` statement instead of raising, so a single exotic construct cannot
prevent a game from being charted.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable

from .script_model import (
    IfEntry,
    MenuItem,
    ScreenElement,
    ScreenInfo,
    ScriptFile,
    Statement,
    Stmt,
)

__all__ = ["parse_script", "parse_file"]

_LABEL_RE = re.compile(r"^label\s+([^\s(:]+)")
_SCREEN_RE = re.compile(r"^screen\s+([^\s(]+)\s*(\(.*?\))?\s*:")
_STYLE_RE = re.compile(r"^style\s+([^\s:]+)(?:\s+is\s+([^\s:]+))?\s*:")
_DEFINE_RE = re.compile(r"^(define|default)\s+(?:([\w.]+)\.)?([\w.]+)\s*=\s*(.*)$", re.S)
_INIT_PYTHON_RE = re.compile(r"^init(?:\s+-?\d+)?\s+python(?:\s+hide)?\s*:")
_INIT_RE = re.compile(r"^init(?:\s+-?\d+)?\s*:")
_PYTHON_RE = re.compile(r"^python(?:\s+hide)?\s*:")
_IF_RE = re.compile(r"^if\s+(.*?)\s*:$")
_ELIF_RE = re.compile(r"^elif\s+(.*?)\s*:$")
_MENU_RE = re.compile(r"^menu(?:\s+.*?)?\s*:$")
_JUMP_RE = re.compile(r"^jump\s+(.+?)\s*$")
_CALL_RE = re.compile(r"^call\s+(.+?)\s*$")
_SAY_PREFIX_RE = re.compile(r"^([A-Za-z_][\w]*(?:\s+[A-Za-z_][\w]*)*)\s*$")

# Statements that may legitimately carry a quoted string.  They must never be
# mistaken for a say statement.
_NON_SAY_KEYWORDS = {
    "$",
    "add",
    "at",
    "bar",
    "call",
    "camera",
    "contain",
    "default",
    "define",
    "elif",
    "else",
    "extend",
    "for",
    "frame",
    "hide",
    "hbox",
    "if",
    "image",
    "imagebutton",
    "imagemap",
    "init",
    "input",
    "jump",
    "key",
    "label",
    "menu",
    "mousearea",
    "nvl",
    "on",
    "pass",
    "pause",
    "play",
    "python",
    "queue",
    "return",
    "scene",
    "screen",
    "show",
    "side",
    "stop",
    "style",
    "text",
    "textbutton",
    "timer",
    "transform",
    "translate",
    "use",
    "vbar",
    "vbox",
    "viewport",
    "voice",
    "while",
    "window",
    "with",
    "for",
}


@dataclass
class _Line:
    number: int
    indent: int
    text: str
    raw: str


def _expand_tabs(raw: str) -> str:
    return raw.replace("\t", "    ")


def _strip_comment(raw: str) -> str:
    """Remove a ``#`` comment that is not inside a string literal."""

    quote = ""
    triple = False
    escaped = False
    result: list[str] = []
    index = 0
    while index < len(raw):
        char = raw[index]
        if escaped:
            result.append(char)
            escaped = False
            index += 1
            continue
        if char == "\\":
            result.append(char)
            escaped = True
            index += 1
            continue
        if quote:
            if triple:
                if raw.startswith(quote * 3, index):
                    result.append(quote * 3)
                    index += 3
                    quote = ""
                    triple = False
                    continue
            elif char == quote:
                result.append(char)
                quote = ""
                index += 1
                continue
            result.append(char)
            index += 1
            continue
        if char in "\"'":
            if raw.startswith(char * 3, index):
                quote = char
                triple = True
                result.append(char * 3)
                index += 3
                continue
            quote = char
            result.append(char)
            index += 1
            continue
        if char == "#":
            break
        result.append(char)
        index += 1
    return "".join(result)


def _scan_string(text: str, start: int) -> tuple[str, int, bool]:
    """Scan a Python/Ren'Py string literal starting at ``start``.

    Returns ``(content, end_index, closed)``.  Triple quoted strings may span
    the newlines that the caller has joined into ``text``.
    """

    quote = text[start]
    triple = text.startswith(quote * 3, start)
    marker = quote * 3 if triple else quote
    index = start + len(marker)
    pieces: list[str] = []
    while index < len(text):
        if text.startswith(marker, index):
            return "".join(pieces), index + len(marker), True
        char = text[index]
        if char == "\\" and index + 1 < len(text):
            pieces.append(char)
            pieces.append(text[index + 1])
            index += 2
            continue
        if char == quote and not triple:
            return "".join(pieces), index + 1, True
        pieces.append(char)
        index += 1
    return "".join(pieces), len(text), False


def _first_string(text: str) -> tuple[int, str, int, bool] | None:
    for index, char in enumerate(text):
        if char in "\"'":
            content, end, closed = _scan_string(text, index)
            return index, content, end, closed
    return None


def _indent_of(raw: str) -> int:
    expanded = _expand_tabs(raw)
    return len(expanded) - len(expanded.lstrip(" "))


def _dedent(lines: Iterable[str]) -> str:
    material = [line for line in lines if line.strip()]
    if not material:
        return ""
    minimum = min(_indent_of(line) for line in material)
    return "\n".join(
        _expand_tabs(line)[minimum:] if line.strip() else "" for line in lines
    )


def _split_properties(lines: Iterable[str]) -> dict[str, str]:
    properties: dict[str, str] = {}
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if ":" in stripped and stripped.endswith(":"):
            continue
        parts = stripped.split(None, 1)
        if not parts:
            continue
        key = parts[0]
        value = parts[1].strip() if len(parts) > 1 else ""
        properties[key] = value
    return properties


def _parse_screen_elements(
    lines: Iterable[str],
) -> tuple[list[ScreenElement], dict[str, str]]:
    """Build a shallow element tree and screen properties from source lines."""

    root: list[ScreenElement] = []
    screen_properties: dict[str, str] = {}
    stack: list[tuple[int, ScreenElement]] = []
    for raw in lines:
        if not raw.strip() or raw.strip().startswith("#"):
            continue
        indent = _indent_of(raw)
        text = raw.strip()
        while stack and indent <= stack[-1][0]:
            stack.pop()
        if text.endswith(":"):
            header = text[:-1].strip()
            kind = header.split(None, 1)[0] if header else "block"
            element = ScreenElement(kind=kind)
            if header.startswith("use "):
                parts = header.split()
                if len(parts) > 1:
                    element.kind = "use"
                    element.target = parts[1].strip("'\"")
            if stack:
                stack[-1][1].children.append(element)
            else:
                root.append(element)
            stack.append((indent, element))
            continue
        parts = text.split(None, 1)
        if not parts:
            continue
        key = parts[0]
        value = parts[1].strip() if len(parts) > 1 else ""
        value = value.strip("'\"") if value[:1] in "'\"" and value[-1:] == value[:1] else value
        if stack:
            stack[-1][1].properties[key] = value
        elif key == "use":
            target = value.split()[0].strip("'\"") if value else ""
            root.append(ScreenElement(kind="use", target=target))
        else:
            screen_properties[key] = value
    return root, screen_properties


class _TextParser:
    def __init__(self, text: str, filename: str) -> None:
        self.filename = filename
        self.raw_lines = text.splitlines()
        self.lines: list[_Line] = []
        for number, raw in enumerate(self.raw_lines):
            expanded = _expand_tabs(raw)
            stripped = _strip_comment(expanded).rstrip()
            if not stripped.strip():
                continue
            indent = len(stripped) - len(stripped.lstrip(" "))
            self.lines.append(_Line(number, indent, stripped.strip(), raw))
        self.index = 0
        self.label_stack: list[str] = []

    # -- low level -----------------------------------------------------------
    def _child_indent(self, parent_indent: int) -> int:
        if self.index < len(self.lines):
            candidate = self.lines[self.index].indent
            if candidate > parent_indent:
                return candidate
        return parent_indent + 4

    def _consume_raw_block(self, parent_line: _Line, parent_indent: int) -> str:
        start = parent_line.number + 1
        end = start
        while end < len(self.raw_lines):
            raw = self.raw_lines[end]
            if raw.strip() and _indent_of(raw) <= parent_indent:
                break
            end += 1
        body = _dedent(self.raw_lines[start:end])
        while self.index < len(self.lines) and self.lines[self.index].number < end:
            self.index += 1
        return body

    def _parse_block(self, indent: int) -> list[Statement]:
        statements: list[Statement] = []
        while self.index < len(self.lines):
            line = self.lines[self.index]
            if line.indent < indent:
                break
            if line.indent > indent:
                # Recover from stray indentation by swallowing the block.
                self.index += 1
                while self.index < len(self.lines) and self.lines[self.index].indent > indent:
                    self.index += 1
                continue
            statements.extend(self._parse_statement(line, indent))
        return statements

    def _resolve_target(self, target: str) -> str:
        target = target.strip()
        if target.startswith(".") and self.label_stack:
            return self.label_stack[-1] + target
        return target

    # -- statements ----------------------------------------------------------
    def _parse_statement(self, line: _Line, indent: int) -> list[Statement]:
        text = line.text
        self.index += 1

        match = _LABEL_RE.match(text)
        if match:
            name = match.group(1)
            if name.startswith(".") and self.label_stack:
                name = self.label_stack[-1] + name
            block_indent = self._child_indent(indent)
            self.label_stack.append(name)
            try:
                block = self._parse_block(block_indent)
            finally:
                self.label_stack.pop()
            return [
                Statement(
                    kind=Stmt.LABEL,
                    line=line.number + 1,
                    filename=self.filename,
                    name=name,
                    block=block,
                )
            ]

        if _MENU_RE.match(text):
            return [self._parse_menu(line, indent)]

        match = _IF_RE.match(text)
        if match:
            entries = [IfEntry(condition=match.group(1), block=self._parse_block(self._child_indent(indent)))]
            while self.index < len(self.lines) and self.lines[self.index].indent == indent:
                candidate = self.lines[self.index]
                elif_match = _ELIF_RE.match(candidate.text)
                if elif_match:
                    self.index += 1
                    entries.append(
                        IfEntry(
                            condition=elif_match.group(1),
                            block=self._parse_block(self._child_indent(indent)),
                        )
                    )
                    continue
                if candidate.text == "else:" or candidate.text.startswith("else "):
                    self.index += 1
                    entries.append(
                        IfEntry(condition="True", block=self._parse_block(self._child_indent(indent)))
                    )
                    continue
                break
            return [Statement(kind=Stmt.IF, line=line.number + 1, filename=self.filename, entries=entries)]

        match = _JUMP_RE.match(text)
        if match:
            target = match.group(1).strip()
            source = ""
            if target.startswith("expression "):
                source, target = target[len("expression ") :], ""
            return [
                Statement(
                    kind=Stmt.JUMP,
                    line=line.number + 1,
                    filename=self.filename,
                    target=self._resolve_target(target),
                    source=source,
                )
            ]

        match = _CALL_RE.match(text)
        if match:
            remainder = match.group(1).strip()
            target = remainder.split(" from ")[0].strip()
            source = ""
            if target.startswith("expression "):
                source, target = target[len("expression ") :], ""
            return [
                Statement(
                    kind=Stmt.CALL,
                    line=line.number + 1,
                    filename=self.filename,
                    target=self._resolve_target(target),
                    source=source,
                )
            ]

        if text == "return" or text.startswith("return "):
            return [Statement(kind=Stmt.RETURN, line=line.number + 1, filename=self.filename)]

        if text == "pass":
            return [Statement(kind=Stmt.PASS, line=line.number + 1, filename=self.filename)]

        if text.startswith("$"):
            return [
                Statement(
                    kind=Stmt.PYTHON,
                    line=line.number + 1,
                    filename=self.filename,
                    source=text[1:].strip(),
                )
            ]

        if _INIT_PYTHON_RE.match(text) or _PYTHON_RE.match(text):
            body = self._consume_raw_block(line, indent)
            return [
                Statement(
                    kind=Stmt.PYTHON,
                    line=line.number + 1,
                    filename=self.filename,
                    source=body,
                    meta={"init": "1" if _INIT_PYTHON_RE.match(text) else ""},
                )
            ]

        if _INIT_RE.match(text):
            block_indent = self._child_indent(indent)
            block = self._parse_block(block_indent)
            return [
                Statement(
                    kind=Stmt.INIT,
                    line=line.number + 1,
                    filename=self.filename,
                    block=block,
                )
            ]

        match = _SCREEN_RE.match(text)
        if match:
            info = self._parse_screen(match.group(1), line, indent, match.group(2) or "()")
            return [
                Statement(
                    kind=Stmt.SCREEN,
                    line=line.number + 1,
                    filename=self.filename,
                    name=info.name,
                    meta={"screen": info},
                )
            ]

        match = _STYLE_RE.match(text)
        if match:
            body = self._consume_raw_block(line, indent)
            properties = _split_properties(body.splitlines())
            return [
                Statement(
                    kind=Stmt.STYLE,
                    line=line.number + 1,
                    filename=self.filename,
                    name=match.group(1),
                    meta={
                        "properties": properties,
                        "parent": match.group(2) or "",
                        "source": body,
                    },
                )
            ]

        match = _DEFINE_RE.match(text)
        if match:
            kind, store, name, value = match.groups()
            full_name = f"{store}.{name}" if store else name
            return [
                Statement(
                    kind=Stmt.DEFINE,
                    line=line.number + 1,
                    filename=self.filename,
                    name=full_name,
                    source=value.strip(),
                    meta={"default": "1" if kind == "default" else ""},
                )
            ]

        if text.startswith("translate ") and text.endswith(":"):
            # Translation blocks repeat existing labels; never treat them as
            # new story structure.
            self.index -= 1
            self._skip_block(line, indent)
            return [Statement(kind=Stmt.OTHER, line=line.number + 1, filename=self.filename, meta={"renpy_type": "translate"})]

        if text.startswith(("init ", "image ", "transform ", "camera ", "show ", "scene ", "hide ", "with ", "play ", "stop ", "queue ", "voice ", "window ", "nvl ", "pause ", "key ", "timer ")):
            if text.endswith(":"):
                self.index -= 1
                self._skip_block(line, indent)
                return [
                    Statement(
                        kind=Stmt.OTHER,
                        line=line.number + 1,
                        filename=self.filename,
                        meta={"renpy_type": text.split(None, 1)[0]},
                    )
                ]
            return [
                Statement(
                    kind=Stmt.OTHER,
                    line=line.number + 1,
                    filename=self.filename,
                    meta={"renpy_type": text.split(None, 1)[0]},
                )
            ]

        say = self._try_say(line, indent)
        if say is not None:
            who, content = say
            return [
                Statement(
                    kind=Stmt.SAY,
                    line=line.number + 1,
                    filename=self.filename,
                    text=content,
                    who=who,
                )
            ]

        if text.endswith(":"):
            self.index -= 1
            self._skip_block(line, indent)
            return [
                Statement(
                    kind=Stmt.OTHER,
                    line=line.number + 1,
                    filename=self.filename,
                    meta={"renpy_type": text.split(None, 1)[0]},
                )
            ]
        return [
            Statement(
                kind=Stmt.OTHER,
                line=line.number + 1,
                filename=self.filename,
                meta={"renpy_type": text.split(None, 1)[0] if text.split() else ""},
            )
        ]

    def _skip_block(self, line: _Line, indent: int) -> None:
        # ``self.index`` currently points at the line after ``line``.
        self.index += 1
        while self.index < len(self.lines) and self.lines[self.index].indent > indent:
            self.index += 1

    def _parse_menu(self, line: _Line, indent: int) -> Statement:
        items: list[MenuItem] = []
        caption = ""
        menu_set: list[str] = []
        if self.index < len(self.lines):
            item_indent = self.lines[self.index].indent
            if item_indent > indent:
                while self.index < len(self.lines) and self.lines[self.index].indent == item_indent:
                    item_line = self.lines[self.index]
                    text = item_line.text
                    if text.startswith("set "):
                        menu_set.append(text[4:].strip())
                        self.index += 1
                        continue
                    found = _first_string(text)
                    if found is None:
                        self.index += 1
                        continue
                    start, content, end, closed = found
                    if not closed:
                        self.index += 1
                        continue
                    remainder = text[end:].strip()
                    condition = ""
                    if " if " in f" {remainder}":
                        after = f" {remainder}"
                        condition = after.split(" if ", 1)[1].strip()
                        if condition.endswith(":"):
                            condition = condition[:-1].strip()
                    has_block = remainder.endswith(":")
                    self.index += 1
                    if not has_block and not condition:
                        caption = content
                        continue
                    block: list[Statement] = []
                    if has_block:
                        block = self._parse_block(self._child_indent(item_indent))
                    items.append(
                        MenuItem(
                            text=content,
                            condition=condition,
                            block=block,
                            line=item_line.number + 1,
                        )
                    )
                    continue
        return Statement(
            kind=Stmt.MENU,
            line=line.number + 1,
            filename=self.filename,
            items=items,
            meta={"caption": caption, "set": "\n".join(menu_set)},
        )

    def _parse_screen(
        self, name: str, line: _Line, indent: int, parameters: str = "()"
    ) -> ScreenInfo:
        body = self._consume_raw_block(line, indent)
        elements, properties = _parse_screen_elements(body.splitlines())
        uses = tuple(
            element.target
            for element in elements
            for child in element.walk()
            if child.kind == "use" and child.target
        )
        return ScreenInfo(
            name=name,
            line=line.number + 1,
            parameters=parameters,
            properties=properties,
            elements=elements,
            source=body,
            use_of=uses,
        )

    def _try_say(self, line: _Line, indent: int) -> tuple[str, str] | None:
        text = line.text
        found = _first_string(text)
        if found is None:
            return None
        start, content, end, closed = found
        prefix = text[:start].strip()
        if prefix:
            if not _SAY_PREFIX_RE.match(prefix):
                return None
            first = prefix.split()[0]
            if first in _NON_SAY_KEYWORDS:
                return None
        if not closed:
            consumed = self._consume_triple_quoted(line, start)
            if consumed is None:
                return None
            content, last_raw_number = consumed
            while self.index < len(self.lines) and self.lines[self.index].number <= last_raw_number:
                self.index += 1
        who = prefix.split()[0] if prefix else ""
        return who, content

    def _consume_triple_quoted(
        self, line: _Line, quote_start: int
    ) -> tuple[str, int] | None:
        """Collect the content of a triple quoted string spanning lines."""

        raw = _expand_tabs(line.raw)
        offset = raw.find(line.text)
        if offset < 0:
            return None
        marker = line.text[quote_start : quote_start + 3]
        if len(marker) != 3 or marker[0] not in ("'", '"') or marker[0] * 3 != marker:
            return None
        current = raw[offset + quote_start + 3 :]
        collected: list[str] = []
        index = line.number
        while True:
            close = current.find(marker)
            if close >= 0:
                collected.append(current[:close])
                return "".join(collected), index
            collected.append(current + "\n")
            index += 1
            if index >= len(self.raw_lines):
                return None
            current = self.raw_lines[index]

    # -- public --------------------------------------------------------------
    def parse(self) -> list[Statement]:
        if not self.lines:
            return []
        return self._parse_block(self.lines[0].indent)


def parse_script(text: str, filename: str = "script.rpy") -> ScriptFile:
    """Parse Ren'Py source text into a normalized :class:`ScriptFile`."""

    parser = _TextParser(text, filename)
    return ScriptFile(
        filename=filename,
        statements=parser.parse(),
        source_format="rpy",
        source_text=text,
    )


def parse_file(path) -> ScriptFile:
    from pathlib import Path

    path = Path(path)
    return parse_script(path.read_text(encoding="utf-8-sig"), filename=path.name)
