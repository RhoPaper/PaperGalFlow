"""JSON theme files: a small, engine independent way to restyle the chart.

A theme is deliberately a plain dictionary of token overrides, so players and
mod authors can keep it next to their game and pass it to ``pgf preview`` /
``pgf install``.  The loader validates every key and colour and fails with a
readable message instead of emitting broken generated code.

Example::

    {
      "name": "sakura",
      "preset": "paper_light",
      "colors": {"accent": "#d96c8a", "panel": "#fff6f8"},
      "typography": {"node_text_size": 24},
      "geometry": {"corner_radius": 18, "border_width": 2},
      "palettes": {"read": {"fill": "#f7dfe7", "border": "#d96c8a"}}
    }
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

from .colors import normalize_color
from .presets import PRESET_NAMES, preset_tokens
from .tokens import NodePalette, StyleTokens, default_palettes

__all__ = [
    "ThemeError",
    "Theme",
    "load_theme",
    "apply_theme",
    "theme_document",
    "write_theme",
]

_MAX_BYTES = 256 * 1024

_COLOR_FIELDS = (
    "background",
    "overlay",
    "panel",
    "panel_light",
    "border",
    "shadow",
    "accent",
    "accent_soft",
    "text",
    "text_dim",
    "text_muted",
    "edge",
    "edge_choice",
    "edge_condition",
    "edge_call",
    "button_fill",
    "button_hover",
    "button_text",
    "close_text",
)
_INT_FIELDS = (
    "title_size",
    "node_text_size",
    "subtitle_size",
    "edge_text_size",
    "legend_size",
    "hint_size",
    "node_width",
    "node_height",
    "node_padding",
    "panel_padding",
    "margin",
    "corner_radius",
    "border_width",
)
_STRING_FIELDS = ("font", "font_bold", "background_image")
_PALETTE_NAMES = ("read", "unread", "locked", "ending", "choice", "condition")
_PALETTE_FIELDS = ("fill", "hover", "border", "text", "strip")

_GROUPS = {
    "colors": set(_COLOR_FIELDS) | {"background_image"},
    "typography": {"font", "font_bold", "title_size", "node_text_size", "subtitle_size",
                   "edge_text_size", "legend_size", "hint_size"},
    "geometry": {"corner_radius", "border_width"},
    "layout": {"node_width", "node_height", "node_padding", "panel_padding", "margin"},
    "edges": {"edge", "edge_choice", "edge_condition", "edge_call"},
    "chrome": {"button_fill", "button_hover", "button_text", "close_text"},
}
_META_KEYS = {"name", "preset", "palettes", "schema", "_comment", "comment"}


class ThemeError(ValueError):
    """A theme file is missing, malformed or contains an invalid override."""


@dataclass
class Theme:
    """A validated theme payload."""

    name: str = ""
    preset: str = ""
    values: dict[str, Any] = field(default_factory=dict)
    palettes: dict[str, dict[str, str]] = field(default_factory=dict)
    source: str = ""

    @property
    def has_color_changes(self) -> bool:
        return any(key in self.values for key in _COLOR_FIELDS)


def _check_mapping(value: Any, where: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ThemeError(f"{where} must be a JSON object")
    return value


def _parse(path: Path, payload: Any) -> Theme:
    data = _check_mapping(payload, "theme")
    theme = Theme(source=str(path))
    allowed = set(_COLOR_FIELDS) | set(_INT_FIELDS) | set(_STRING_FIELDS) | set(_GROUPS) | _META_KEYS

    for key in data:
        if key not in allowed:
            raise ThemeError(f"unknown theme key: {key!r}")

    name = data.get("name", "")
    if name and not isinstance(name, str):
        raise ThemeError("name must be a string")
    theme.name = str(name).strip()

    preset = data.get("preset", "")
    if preset:
        if not isinstance(preset, str) or preset not in PRESET_NAMES:
            raise ThemeError(
                f"preset must be one of {', '.join(PRESET_NAMES)}; got {preset!r}"
            )
        theme.preset = preset

    overrides: dict[str, Any] = {}
    for group, keys in _GROUPS.items():
        if group not in data:
            continue
        values = _check_mapping(data[group], group)
        for key, value in values.items():
            if key not in keys:
                raise ThemeError(f"unknown key {key!r} in {group}")
            overrides[key] = value
    for key in list(_COLOR_FIELDS) + list(_INT_FIELDS) + list(_STRING_FIELDS):
        if key in data:
            overrides[key] = data[key]

    for key, value in overrides.items():
        if key in _COLOR_FIELDS:
            color = normalize_color(value)
            if not color:
                raise ThemeError(f"{key} is not a valid colour: {value!r}")
            theme.values[key] = color
        elif key == "background_image":
            if not isinstance(value, str):
                raise ThemeError("background_image must be a string")
            theme.values[key] = value.strip()
        elif key in _STRING_FIELDS:
            if not isinstance(value, str):
                raise ThemeError(f"{key} must be a string")
            theme.values[key] = value.strip()
        else:
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ThemeError(f"{key} must be an integer")
            if int(value) < 0:
                raise ThemeError(f"{key} must not be negative")
            theme.values[key] = int(value)

    raw_palettes = data.get("palettes", {})
    if raw_palettes:
        raw_palettes = _check_mapping(raw_palettes, "palettes")
        for state, values in raw_palettes.items():
            if state not in _PALETTE_NAMES:
                raise ThemeError(
                    f"unknown palette {state!r}; expected {', '.join(_PALETTE_NAMES)}"
                )
            values = _check_mapping(values, f"palettes.{state}")
            palette: dict[str, str] = {}
            for key, value in values.items():
                if key not in _PALETTE_FIELDS:
                    raise ThemeError(f"unknown key {key!r} in palettes.{state}")
                color = normalize_color(value)
                if not color:
                    raise ThemeError(f"palettes.{state}.{key} is not a valid colour")
                palette[key] = color
            theme.palettes[state] = palette
    return theme


def load_theme(path: str | Path) -> Theme:
    """Read and validate a JSON theme file."""

    source = Path(path).expanduser()
    try:
        raw = source.read_bytes()
    except OSError as exc:
        raise ThemeError(f"could not read theme {source}: {exc}") from exc
    if len(raw) > _MAX_BYTES:
        raise ThemeError(f"theme file is too large (limit {_MAX_BYTES} bytes)")
    try:
        payload = json.loads(raw.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ThemeError(f"could not parse theme {source}: {exc}") from exc
    return _parse(source, payload)


def apply_theme(tokens: StyleTokens, theme: Theme | Mapping[str, Any]) -> StyleTokens:
    """Return a copy of *tokens* with the theme overrides applied."""

    if not isinstance(theme, Theme):
        theme = _parse(Path("<inline>"), theme)

    base = preset_tokens(theme.preset) if theme.preset else tokens
    result = StyleTokens.from_dict(base.to_dict())
    result.name = theme.name or (base.name + "_custom")
    if theme.values:
        for key, value in theme.values.items():
            setattr(result, key, value)

    if theme.preset or theme.has_color_changes:
        result.palettes = default_palettes(result)

    for state, values in theme.palettes.items():
        current = result.palettes.get(state) or result.palette(state)
        payload = current.to_dict()
        payload.update(values)
        result.palettes[state] = NodePalette.from_dict(payload)

    result.source = "theme" if theme.preset else (base.source + "+theme")
    result.confidence = 1.0 if theme.preset else max(base.confidence, 0.8)
    result.notes = list(base.notes)
    result.notes.append(f"theme {result.name}" + (f" from {theme.source}" if theme.source else ""))
    if theme.preset:
        result.notes.append(f"theme base preset {theme.preset}")
    return result


def theme_document(tokens: StyleTokens) -> dict[str, Any]:
    """Return a complete, editable theme document for *tokens*."""

    return {
        "schema": 1,
        "name": tokens.name,
        "colors": {key: getattr(tokens, key) for key in _COLOR_FIELDS},
        "typography": {
            key: getattr(tokens, key)
            for key in ("font", "font_bold", "title_size", "node_text_size",
                        "subtitle_size", "edge_text_size", "legend_size", "hint_size")
        },
        "geometry": {
            "corner_radius": tokens.corner_radius,
            "border_width": tokens.border_width,
        },
        "layout": {
            key: getattr(tokens, key)
            for key in ("node_width", "node_height", "node_padding", "panel_padding", "margin")
        },
        "edges": {
            key: getattr(tokens, key)
            for key in ("edge", "edge_choice", "edge_condition", "edge_call")
        },
        "palettes": {state: tokens.palette(state).to_dict() for state in _PALETTE_NAMES},
    }


def write_theme(path: str | Path, tokens: StyleTokens) -> Path:
    """Write an editable theme document and return the path."""

    target = Path(path).expanduser()
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = theme_document(tokens)
    target.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return target
