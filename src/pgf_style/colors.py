"""Colour helpers used by the style layer.

Everything returns plain ``#rrggbb`` / ``#rrggbbaa`` strings so the tokens can
be serialised to JSON and embedded into generated Ren'Py code without a colour
library dependency.
"""

from __future__ import annotations

import ast
import re
from typing import Iterable

__all__ = [
    "parse_color",
    "normalize_color",
    "to_hex",
    "mix",
    "lighten",
    "darken",
    "with_alpha",
    "luminance",
    "contrast_text",
    "saturate",
    "contrast_ratio",
]

_HEX_RE = re.compile(r"^#?([0-9a-fA-F]{3,8})$")
_RGB_RE = re.compile(r"^rgba?\s*\(([^)]*)\)$", re.I)

_RGBA = tuple[int, int, int, int]


def parse_color(value: object) -> _RGBA | None:
    """Parse a Ren'Py/HTML colour expression into ``(r, g, b, a)``.

    Accepts ``"#0099ff"``, ``"#09f"``, ``"#0099ffcc"``, ``"#0099ff7f"``,
    ``(r, g, b)`` / ``(r, g, b, a)`` tuples and ``rgb(...)`` strings.
    """

    if isinstance(value, (tuple, list)) and len(value) in (3, 4):
        try:
            channels = [max(0, min(255, int(component))) for component in value]
        except (TypeError, ValueError):
            return None
        if len(channels) == 3:
            channels.append(255)
        return channels[0], channels[1], channels[2], channels[3]

    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    if (text[0] == text[-1] and text[0] in "'\"") and len(text) >= 2:
        try:
            literal = ast.literal_eval(text)
        except (ValueError, SyntaxError):
            literal = text[1:-1]
        if isinstance(literal, str):
            return parse_color(literal)
        if isinstance(literal, tuple):
            return parse_color(literal)
        return None
    rgb_match = _RGB_RE.match(text)
    if rgb_match:
        parts = [part.strip() for part in rgb_match.group(1).split(",")]
        if len(parts) in (3, 4):
            try:
                channels = [int(float(part)) for part in parts]
            except ValueError:
                return None
            if len(channels) == 3:
                channels.append(255)
            return tuple(max(0, min(255, channel)) for channel in channels)  # type: ignore[return-value]
        return None
    hex_match = _HEX_RE.match(text)
    if not hex_match:
        return None
    digits = hex_match.group(1)
    if len(digits) == 3:
        digits = "".join(ch * 2 for ch in digits) + "ff"
    elif len(digits) == 4:
        digits = "".join(ch * 2 for ch in digits)
    elif len(digits) == 6:
        digits += "ff"
    elif len(digits) != 8:
        return None
    try:
        return (
            int(digits[0:2], 16),
            int(digits[2:4], 16),
            int(digits[4:6], 16),
            int(digits[6:8], 16),
        )
    except ValueError:
        return None


def to_hex(rgba: _RGBA, *, alpha: bool = True) -> str:
    r, g, b, a = rgba
    if alpha and a < 255:
        return f"#{r:02x}{g:02x}{b:02x}{a:02x}"
    return f"#{r:02x}{g:02x}{b:02x}"


def normalize_color(value: object, default: str = "") -> str:
    parsed = parse_color(value)
    if parsed is None:
        return default
    return to_hex(parsed)


def mix(first: str, second: str, amount: float) -> str:
    """Linear interpolation; ``amount=0`` is ``first``, ``1`` is ``second``."""

    a = parse_color(first)
    b = parse_color(second)
    if a is None or b is None:
        return first
    amount = max(0.0, min(1.0, amount))
    return to_hex(
        (
            int(round(a[0] + (b[0] - a[0]) * amount)),
            int(round(a[1] + (b[1] - a[1]) * amount)),
            int(round(a[2] + (b[2] - a[2]) * amount)),
            int(round(a[3] + (b[3] - a[3]) * amount)),
        )
    )


def lighten(color: str, amount: float) -> str:
    return mix(color, "#ffffff", amount)


def darken(color: str, amount: float) -> str:
    return mix(color, "#000000", amount)


def with_alpha(color: str, amount: float) -> str:
    parsed = parse_color(color)
    if parsed is None:
        return color
    alpha = max(0, min(255, int(round(amount * 255))))
    return to_hex((parsed[0], parsed[1], parsed[2], alpha))


def luminance(color: str) -> float:
    parsed = parse_color(color)
    if parsed is None:
        return 0.0

    def channel(value: int) -> float:
        value = value / 255.0
        return value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4

    r, g, b, _a = parsed
    return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b)


def contrast_ratio(first: str, second: str) -> float:
    """WCAG contrast ratio between two colours (1..21)."""

    a = luminance(first)
    b = luminance(second)
    lighter, darker = max(a, b), min(a, b)
    return (lighter + 0.05) / (darker + 0.05)


def contrast_text(background: str, light: str = "#f4f7fb", dark: str = "#141821") -> str:
    return light if luminance(background) < 0.45 else dark


def saturate(color: str, amount: float) -> str:
    """Push a colour away from its greyscale equivalent."""

    parsed = parse_color(color)
    if parsed is None:
        return color
    r, g, b, a = parsed
    grey = int(round(0.299 * r + 0.587 * g + 0.114 * b))
    amount = max(0.0, amount)
    return to_hex(
        (
            max(0, min(255, int(round(grey + (r - grey) * amount)))),
            max(0, min(255, int(round(grey + (g - grey) * amount)))),
            max(0, min(255, int(round(grey + (b - grey) * amount)))),
            a,
        )
    )


def pick_first(*values: object, default: str = "") -> str:
    for value in values:
        normalized = normalize_color(value)
        if normalized:
            return normalized
    return default


__all__ += ["pick_first"]
