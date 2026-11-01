"""Translate style tokens into Ren'Py style definitions.

This is the only place in :mod:`pgf_style` that knows the target engine.  It
returns plain data plus a snippet of Ren'Py ``style`` statements so the Ren'Py
adapter can embed them verbatim; no other engine needs to be considered here.
"""

from __future__ import annotations

from dataclasses import dataclass

from .tokens import StyleTokens

__all__ = ["RenpyTheme", "build_theme", "style_source"]


@dataclass(frozen=True)
class RenpyTheme:
    constants: dict[str, object]
    style_blocks: str

    @property
    def style_dict(self) -> dict[str, object]:
        return dict(self.constants)


def _palette(tokens: StyleTokens, key: str) -> dict[str, str]:
    palette = tokens.palette(key)
    return {
        "fill": palette.fill,
        "hover": palette.hover,
        "border": palette.border,
        "text": palette.text,
        "strip": palette.strip,
    }


def build_theme(tokens: StyleTokens) -> RenpyTheme:
    """Return the data and style blocks the Ren'Py emitter needs."""

    style = {
        "font": tokens.font,
        "font_bold": tokens.font_bold or tokens.font,
        "title_size": tokens.title_size,
        "node_text_size": tokens.node_text_size,
        "subtitle_size": tokens.subtitle_size,
        "edge_text_size": tokens.edge_text_size,
        "legend_size": tokens.legend_size,
        "hint_size": tokens.hint_size,
        "node_width": tokens.node_width,
        "node_height": tokens.node_height,
        "node_padding": tokens.node_padding,
        "panel_padding": tokens.panel_padding,
        "margin": tokens.margin,
        "background_image": tokens.background_image,
        "colors": {
            "background": tokens.background,
            "overlay": tokens.overlay,
            "panel": tokens.panel,
            "panel_light": tokens.panel_light,
            "border": tokens.border,
            "shadow": tokens.shadow,
            "accent": tokens.accent,
            "accent_soft": tokens.accent_soft,
            "text": tokens.text,
            "text_dim": tokens.text_dim,
            "text_muted": tokens.text_muted,
            "button_fill": tokens.button_fill,
            "button_hover": tokens.button_hover,
            "button_text": tokens.button_text,
            "close_text": tokens.close_text,
        },
        "palettes": {
            key: _palette(tokens, key)
            for key in ("read", "unread", "locked", "ending", "choice", "condition")
        },
        "edges": {
            "flow": tokens.edge,
            "choice": tokens.edge_choice,
            "condition": tokens.edge_condition,
            "call": tokens.edge_call,
        },
        "source": tokens.source,
        "name": tokens.name,
        "confidence": round(tokens.confidence, 3),
        "notes": list(tokens.notes),
    }
    return RenpyTheme(constants={"PGF_STYLE": style}, style_blocks=style_source(tokens))


def style_source(tokens: StyleTokens) -> str:
    """Return Ren'Py ``style`` blocks for the generated screen."""

    font = f'    font "{tokens.font}"\n' if tokens.font else ""
    font_bold = f'    font "{tokens.font_bold or tokens.font}"\n' if tokens.font_bold else font
    return (
        "style pgf_title_text:\n"
        f"{font_bold}"
        f"    size {tokens.title_size}\n"
        f'    color "{tokens.text}"\n\n'
        "style pgf_node_text:\n"
        f"{font}"
        f"    size {tokens.node_text_size}\n\n"
        "style pgf_node_subtitle:\n"
        f"{font}"
        f"    size {tokens.subtitle_size}\n"
        f'    color "{tokens.text_muted}"\n\n'
        "style pgf_edge_text:\n"
        f"{font}"
        f"    size {tokens.edge_text_size}\n"
        f'    color "{tokens.text_dim}"\n'
        f'    outlines [(1, "{tokens.background}dd", 0, 0)]\n\n'
        "style pgf_legend_text:\n"
        f"{font}"
        f"    size {tokens.legend_size}\n"
        f'    color "{tokens.text_dim}"\n\n'
        "style pgf_small_text:\n"
        f"{font}"
        f"    size {tokens.hint_size}\n"
        f'    color "{tokens.text_muted}"\n\n'
        "style pgf_chrome_text:\n"
        f"{font}"
        f"    size {tokens.legend_size}\n"
        f'    idle_color "{tokens.button_text}"\n'
        f'    hover_color "{tokens.accent}"\n\n'
        "style pgf_chrome_button:\n"
        f'    background Solid("{tokens.button_fill}")\n'
        f'    hover_background Solid("{tokens.button_hover}")\n'
        "    padding (12, 4)\n"
    )
