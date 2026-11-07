"""Theme facade for the core/CLI.

The token model lives in :mod:`pgf_style`; the CLI imports this module so the
command layer still only talks to ``pgf_core``.
"""

from __future__ import annotations

from pgf_style import (
    Theme,
    ThemeError,
    apply_theme,
    load_theme,
    preset_tokens,
    theme_document,
    write_theme,
)

__all__ = [
    "Theme",
    "ThemeError",
    "apply_theme",
    "load_theme",
    "preset_tokens",
    "theme_document",
    "write_theme",
]
