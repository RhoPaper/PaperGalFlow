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
from .theme import (
    Theme,
    ThemeError,
    apply_theme,
    load_theme,
    theme_document,
    write_theme,
)
from .tokens import NodePalette, StyleTokens, style_tokens
from .vision import (
    OpenAICompatibleVision,
    VisionConfig,
    VisionError,
    VisionStyle,
    fuse_vision,
    vision_backend,
    vision_tokens,
)

__all__ = [
    "PRESET_NAMES",
    "NodePalette",
    "OpenAICompatibleVision",
    "RenpyTheme",
    "StyleEvidence",
    "StyleTokens",
    "Theme",
    "ThemeError",
    "UiSample",
    "VisionConfig",
    "VisionError",
    "VisionStyle",
    "apply_theme",
    "build_theme",
    "contrast_ratio",
    "contrast_text",
    "darken",
    "fuse_vision",
    "lighten",
    "load_theme",
    "luminance",
    "mix",
    "normalize_color",
    "parse_color",
    "preset_tokens",
    "resolve_ui_samples",
    "saturate",
    "style_source",
    "style_tokens",
    "theme_document",
    "to_hex",
    "tokens_from_evidence",
    "vision_backend",
    "vision_tokens",
    "write_theme",
    "with_alpha",
]
