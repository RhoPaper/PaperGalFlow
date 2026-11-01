"""pgf-style -- game style extraction, tokens and engine theme translation."""

from __future__ import annotations

from .colors import (
    contrast_ratio,
    contrast_text,
    darken,
    lighten,
    luminance,
    mix,
    normalize_color,
    parse_color,
    saturate,
    to_hex,
    with_alpha,
)
from .evidence import StyleEvidence, UiSample
from .presets import PRESET_NAMES, preset_tokens
from .renpy_theme import RenpyTheme, build_theme, style_source
from .sources import resolve_ui_samples, tokens_from_evidence
from .tokens import NodePalette, StyleTokens, style_tokens

__all__ = [
    "PRESET_NAMES",
    "NodePalette",
    "RenpyTheme",
    "StyleEvidence",
    "StyleTokens",
    "UiSample",
    "build_theme",
    "contrast_ratio",
    "contrast_text",
    "darken",
    "lighten",
    "luminance",
    "mix",
    "normalize_color",
    "parse_color",
    "preset_tokens",
    "resolve_ui_samples",
    "saturate",
    "style_source",
    "style_tokens",
    "to_hex",
    "tokens_from_evidence",
    "with_alpha",
]
