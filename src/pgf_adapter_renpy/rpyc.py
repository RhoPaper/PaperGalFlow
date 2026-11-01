"""Read compiled Ren'Py scripts (``.rpyc``) without running game code.

A ``.rpyc`` is a zlib compressed pickle of ``(metadata, statements)``.  Loading
that pickle would execute arbitrary code, so this module unpickles into inert
stub classes and maps a handful of Ren'Py classes to safe equivalents.  The
resulting objects only carry data; nothing from the game is called.

The normalized :class:`~.script_model.ScriptFile` produced here is identical
in shape to the one produced by the text parser, which is what lets the rest of
the adapter stay unaware of whether the game shipped sources or only bytecode.
"""

from __future__ import annotations

import copyreg
import io
import pickle
import struct
import zlib
from collections import OrderedDict, defaultdict
from typing import Any

from pgf_core.errors import PgfError

from .script_model import (
    IfEntry,
    MenuItem,
    ScreenElement,
    ScreenInfo,
    ScriptFile,
    Statement,
    Stmt,
)

__all__ = [
    "RpycError",
    "RPYC2_HEADER",
    "extract_payload",
    "decode_rpyc",
    "normalize_statement_block",
]

RPYC2_HEADER = b"RENPY RPC2"
_SLOT_SIZE = 12
_HEADER_PEEK = 1024


class RpycError(PgfError):
    """A compiled script is corrupt or uses an unsupported container."""


# ---------------------------------------------------------------------------
# safe unpickling
# ---------------------------------------------------------------------------


class _Stub:
    """Inert placeholder for any Ren'Py class found in the pickle."""

    def __new__(cls, *args: Any, **kwargs: Any) -> "_Stub":
        obj = object.__new__(cls)
        obj._args = args
        obj._kwargs = kwargs
        return obj

    def __init__(self, *_args: Any, **_kwargs: Any) -> None:
        pass

    def __setstate__(self, state: Any) -> None:
        self._state = state
        if (
            isinstance(state, tuple)
            and len(state) == 2
            and isinstance(state[1], dict)
        ):
            state = state[1]
        if isinstance(state, dict):
            self.__dict__.update(state)

    def __getattr__(self, name: str) -> Any:
        if name.startswith("__"):
            raise AttributeError(name)
        return None

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<{type(self).__name__}>"


class _PyExpr(str):
    """Ren'Py's Python expression subclass: a plain string for our purposes."""

    def __new__(cls, value: str = "", *_args: Any, **_kwargs: Any) -> "_PyExpr":
        return str.__new__(cls, value)

    def __init__(self, *_args: Any, **_kwargs: Any) -> None:
        pass


class _PyCode(_Stub):
    """Ren'Py's ``PyCode``: its state is a tuple we unpack into attributes."""

    def __setstate__(self, state: Any) -> None:
        self._state = state
        if (
            isinstance(state, tuple)
            and len(state) >= 4
            and isinstance(state[1], str)
        ):
            self.source = state[1]
            location = state[2]
            if isinstance(location, (tuple, list)) and len(location) >= 2:
                self.filename = str(location[0])
                self.linenumber = int(location[1])
            self.mode = str(state[3])
            return
        super().__setstate__(state)


class _Sentinel(_Stub):
    def __new__(cls, name: Any = "", *_args: Any, **_kwargs: Any) -> "_Sentinel":
        obj = object.__new__(cls)
        obj.name = name
        return obj


_STUB_CACHE: dict[tuple[str, str], type] = {}
_SAFE_BUILTINS = {
    "str": str,
    "bytes": bytes,
    "bytearray": bytearray,
    "int": int,
    "float": float,
    "bool": bool,
    "complex": complex,
    "dict": dict,
    "list": list,
    "tuple": tuple,
    "set": set,
    "frozenset": frozenset,
    "object": object,
    "slice": slice,
}
_REVERTABLE = {
    "RevertableDict": dict,
    "RevertableList": list,
    "RevertableSet": set,
    "RevertableObject": object,
    "RevertableTuple": tuple,
}


def _stub_class(module: str, name: str) -> type:
    key = (module, name)
    if key not in _STUB_CACHE:
        _STUB_CACHE[key] = type(name, (_Stub,), {"__module__": module})
    return _STUB_CACHE[key]


class _SafeUnpickler(pickle.Unpickler):
    """Unpickler that cannot import or call anything dangerous."""

    def find_class(self, module: str, name: str) -> Any:
        if module == "builtins" and name in _SAFE_BUILTINS:
            return _SAFE_BUILTINS[name]
        if module == "copyreg" and name == "_reconstructor":
            return copyreg._reconstructor
        if module == "collections" and name in ("OrderedDict", "defaultdict"):
            return {"OrderedDict": OrderedDict, "defaultdict": defaultdict}[name]
        if module == "renpy.revertable":
            return _REVERTABLE.get(name, dict)
        if module == "renpy.object" and name == "Sentinel":
            return _Sentinel
        if module == "renpy.ast" and name == "PyCode":
            return _PyCode
        if module == "renpy.astsupport" and name == "PyExpr":
            return _PyExpr
        # Every other Ren'Py class becomes an inert data bag.
        return _stub_class(module, name)

    def persistent_load(self, pid: Any) -> Any:  # pragma: no cover - defensive
        return None


# ---------------------------------------------------------------------------
# container format
# ---------------------------------------------------------------------------


def extract_payload(blob: bytes) -> bytes:
    """Return the pickled ``(metadata, statements)`` payload of a ``.rpyc``."""

    if not blob.startswith(RPYC2_HEADER):
        # Legacy format: the whole file is a zlib compressed pickle.
        try:
            return zlib.decompress(blob)
        except zlib.error as exc:
            raise RpycError(f"not a Ren'Py compiled script: {exc}") from exc

    header = blob[:_HEADER_PEEK]
    if len(header) < len(RPYC2_HEADER) + _SLOT_SIZE:
        raise RpycError("truncated RPYC2 header")

    slots: dict[int, tuple[int, int]] = {}
    position = len(RPYC2_HEADER)
    while position + _SLOT_SIZE <= len(header):
        slot, start, length = struct.unpack("<III", header[position : position + _SLOT_SIZE])
        position += _SLOT_SIZE
        if slot == 0:
            break
        slots[slot] = (start, length)

    # Slot 2 holds the statically transformed statements, slot 1 the raw ones.
    for wanted in (2, 1):
        if wanted not in slots:
            continue
        start, length = slots[wanted]
        if length <= 0 or start + length > len(blob):
            continue
        try:
            return zlib.decompress(blob[start : start + length])
        except zlib.error:
            continue
    raise RpycError("no usable statement slot in .rpyc file")


def _load_pickle(payload: bytes) -> tuple[dict[str, Any], list[Any]]:
    try:
        data = _SafeUnpickler(io.BytesIO(payload)).load()
    except Exception as exc:
        raise RpycError(f"could not unpickle script data: {exc}") from exc
    if not isinstance(data, (tuple, list)) or len(data) != 2:
        raise RpycError("compiled script payload is not a (metadata, statements) pair")
    metadata, statements = data
    if not isinstance(metadata, dict):
        metadata = {}
    if not isinstance(statements, list):
        raise RpycError("compiled script statements are not a list")
    return metadata, statements


# ---------------------------------------------------------------------------
# normalization helpers
# ---------------------------------------------------------------------------


def _expr(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return str(value)
    args = getattr(value, "_args", None)
    if isinstance(args, tuple) and args:
        return str(args[0])
    return str(value)


def _literal(value: Any) -> str:
    text = _expr(value).strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in ("'", '"'):
        return text[1:-1]
    return text


def _location(node: Any) -> tuple[str, int]:
    location = getattr(node, "location", None)
    if isinstance(location, (tuple, list)) and len(location) >= 2:
        return str(location[0]), int(location[1] or 0)
    filename = getattr(node, "filename", None)
    line = getattr(node, "linenumber", None)
    return str(filename or ""), int(line or 0)


def _code_source(node: Any) -> str:
    code = getattr(node, "code", None)
    source = getattr(code, "source", None)
    return _expr(source)


def _normalize_block(nodes: Any) -> list[Statement]:
    if not isinstance(nodes, (list, tuple)):
        return []
    result: list[Statement] = []
    for node in nodes:
        statement = _normalize_node(node)
        if statement is not None:
            result.append(statement)
    return result


def normalize_statement_block(nodes: Any) -> list[Statement]:
    """Public wrapper used by tests and other adapter modules."""

    return _normalize_block(nodes)


def _normalize_node(node: Any) -> Statement | None:
    if node is None:
        return None
    cls = type(node).__name__
    filename, line = _location(node)

    if cls == "Label":
        name = _expr(getattr(node, "_name", None)) or _literal(getattr(node, "name", None))
        return Statement(
            kind=Stmt.LABEL,
            line=line,
            filename=filename,
            name=name,
            block=_normalize_block(getattr(node, "block", None)),
            meta={"parameters": "1" if getattr(node, "parameters", None) is not None else ""},
        )

    if cls in ("Say", "TranslateSay"):
        return Statement(
            kind=Stmt.SAY,
            line=line,
            filename=filename,
            text=_expr(getattr(node, "what", None)),
            who=_expr(getattr(node, "who", None)),
        )

    if cls == "Menu":
        raw_items = getattr(node, "items", None) or []
        items: list[MenuItem] = []
        caption = ""
        for index, raw in enumerate(raw_items):
            if not isinstance(raw, (tuple, list)) or len(raw) < 3:
                continue
            text = _literal(raw[0])
            condition = _expr(raw[1])
            if condition == "True":
                condition = ""
            block = _normalize_block(raw[2])
            item_line = line
            if getattr(node, "has_caption", False) and index == 0 and raw[2] is None:
                caption = text
                continue
            items.append(
                MenuItem(text=text, condition=condition, block=block, line=item_line)
            )
        return Statement(
            kind=Stmt.MENU,
            line=line,
            filename=filename,
            items=items,
            meta={"caption": caption},
        )

    if cls == "If":
        entries: list[IfEntry] = []
        for raw in getattr(node, "entries", None) or []:
            if isinstance(raw, (tuple, list)) and len(raw) >= 2:
                entries.append(IfEntry(condition=_expr(raw[0]), block=_normalize_block(raw[1])))
            else:
                entries.append(
                    IfEntry(
                        condition=_expr(getattr(raw, "condition", None)),
                        block=_normalize_block(getattr(raw, "block", None)),
                    )
                )
        return Statement(kind=Stmt.IF, line=line, filename=filename, entries=entries)

    if cls in ("Jump", "Call"):
        target = getattr(node, "label", None) if cls == "Call" else getattr(node, "target", None)
        expression = _expr(getattr(node, "expression", None))
        return Statement(
            kind=Stmt.JUMP if cls == "Jump" else Stmt.CALL,
            line=line,
            filename=filename,
            target=_expr(target),
            source=expression,
            meta={"arguments": _expr(getattr(node, "arguments", None))},
        )

    if cls == "Return":
        return Statement(kind=Stmt.RETURN, line=line, filename=filename)

    if cls in ("Python", "EarlyPython"):
        return Statement(
            kind=Stmt.PYTHON,
            line=line,
            filename=filename,
            source=_code_source(node),
            meta={"store": _expr(getattr(node, "store", None))},
        )

    if cls in ("Define", "Default"):
        store = _expr(getattr(node, "store", None))
        name = _expr(getattr(node, "varname", None))
        if store.startswith("store."):
            store = store[len("store.") :]
        elif store == "store":
            store = ""
        full_name = f"{store}.{name}" if store else name
        return Statement(
            kind=Stmt.DEFINE,
            line=line,
            filename=filename,
            name=full_name,
            source=_code_source(node),
            meta={
                "store": _expr(getattr(node, "store", None)),
                "default": "1" if cls == "Default" else "",
            },
        )

    if cls == "Style":
        properties = _screen_properties(getattr(node, "properties", None))
        return Statement(
            kind=Stmt.STYLE,
            line=line,
            filename=filename,
            name=_literal(getattr(node, "style_name", None)),
            meta={
                "properties": properties,
                "parent": _literal(getattr(node, "parent", None)),
                "clear": "1" if getattr(node, "clear", False) else "",
            },
        )

    if cls == "Screen":
        screen = getattr(node, "screen", None)
        info = _screen_info(screen) if screen is not None else ScreenInfo(name="")
        info.line = line
        return Statement(
            kind=Stmt.SCREEN,
            line=line,
            filename=filename,
            name=info.name,
            meta={"screen": info},
        )

    if cls == "Init":
        return Statement(
            kind=Stmt.INIT,
            line=line,
            filename=filename,
            block=_normalize_block(getattr(node, "block", None)),
            meta={"priority": _expr(getattr(node, "priority", None))},
        )

    if cls == "Pass":
        return Statement(kind=Stmt.PASS, line=line, filename=filename)

    block = getattr(node, "block", None)
    normalized_block = _normalize_block(block)
    if normalized_block:
        return Statement(
            kind=Stmt.OTHER,
            line=line,
            filename=filename,
            block=normalized_block,
            meta={"renpy_type": cls},
        )
    return Statement(kind=Stmt.OTHER, line=line, filename=filename, meta={"renpy_type": cls})


# ---------------------------------------------------------------------------
# screen language conversion
# ---------------------------------------------------------------------------


def _screen_properties(raw: Any) -> dict[str, str]:
    properties: dict[str, str] = {}
    if isinstance(raw, dict):
        for key, value in raw.items():
            properties[str(key)] = _expr(value)
    elif isinstance(raw, (list, tuple)):
        for item in raw:
            if isinstance(item, (tuple, list)) and len(item) >= 2:
                properties[str(item[0])] = _expr(item[1])
    return properties


def _screen_element(node: Any) -> ScreenElement | None:
    if node is None:
        return None
    cls = type(node).__name__
    line = _location(node)[1]
    properties = _screen_properties(getattr(node, "keyword", None))
    children: list[ScreenElement] = []

    if cls == "SLDisplayable":
        kind = _literal(getattr(node, "name", None)) or "displayable"
        for child in getattr(node, "children", None) or []:
            element = _screen_element(child)
            if element is not None:
                children.append(element)
        child = getattr(node, "child", None)
        if child is not None and type(child).__name__.startswith("SL"):
            element = _screen_element(child)
            if element is not None:
                children.append(element)
        positional = getattr(node, "positional", None) or []
        text = _expr(positional[0]) if positional else ""
        return ScreenElement(kind=kind, line=line, properties=properties, children=children, text=text)

    if cls == "SLUse":
        target = _literal(getattr(node, "target", None))
        block = getattr(node, "block", None)
        if block is not None:
            element = _screen_element(block)
            if element is not None:
                children.extend(element.children or [element])
        return ScreenElement(kind="use", line=line, properties=properties, children=children, target=target)

    if cls in ("SLIf", "SLShowIf"):
        for entry in getattr(node, "entries", None) or []:
            condition = ""
            block = None
            if isinstance(entry, (tuple, list)) and len(entry) >= 2:
                condition, block = _expr(entry[0]), entry[1]
            else:
                condition = _expr(getattr(entry, "condition", None))
                block = getattr(entry, "block", None)
            block_children = getattr(block, "children", None) or []
            for child in block_children:
                element = _screen_element(child)
                if element is not None:
                    if condition and not element.condition:
                        element.condition = condition
                    children.append(element)
        return ScreenElement(kind="if", line=line, properties=properties, children=children)

    if cls in ("SLBlock", "SLATL"):
        for child in getattr(node, "children", None) or []:
            element = _screen_element(child)
            if element is not None:
                children.append(element)
        return ScreenElement(kind="block", line=line, properties=properties, children=children)

    # SLFor, SLTransform, SLText and friends: keep children when present.
    for attribute in ("children", "entries"):
        for child in getattr(node, attribute, None) or []:
            if isinstance(child, (tuple, list)):
                for sub in child:
                    element = _screen_element(sub)
                    if element is not None:
                        children.append(element)
            else:
                element = _screen_element(child)
                if element is not None:
                    children.append(element)
    return ScreenElement(
        kind=cls.removeprefix("SL").lower() if cls.startswith("SL") else cls.lower(),
        line=line,
        properties=properties,
        children=children,
        text=_expr(getattr(node, "text", None)),
    )


def _screen_info(screen: Any) -> ScreenInfo:
    name = _literal(getattr(screen, "name", None))
    properties = _screen_properties(getattr(screen, "keyword", None))
    elements: list[ScreenElement] = []
    for child in getattr(screen, "children", None) or []:
        element = _screen_element(child)
        if element is not None:
            elements.append(element)
    uses = tuple(
        child.target
        for element in elements
        for child in element.walk()
        if child.kind == "use" and child.target
    )
    return ScreenInfo(
        name=name,
        line=_location(screen)[1],
        properties=properties,
        elements=elements,
        use_of=uses,
    )


# ---------------------------------------------------------------------------
# public API
# ---------------------------------------------------------------------------


def decode_rpyc(blob: bytes, filename: str = "") -> ScriptFile:
    """Decode a ``.rpyc`` file into a normalized :class:`ScriptFile`."""

    payload = extract_payload(blob)
    metadata, raw_statements = _load_pickle(payload)
    statements = normalize_statement_block(raw_statements)
    if not filename:
        for statement in statements:
            if statement.filename:
                filename = statement.filename
                break
    return ScriptFile(
        filename=filename,
        statements=statements,
        source_format="rpyc",
        metadata=metadata,
    )
