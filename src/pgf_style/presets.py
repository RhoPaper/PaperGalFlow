"""Built in fallback palettes.

The preset is the last link of the style degradation chain: it is used when a
game has no readable GUI definitions and no sampleable UI assets.
"""

from __future__ import annotations

from .tokens import NodePalette, StyleTokens, style_tokens

__all__ = ["PRESET_NAMES", "preset_tokens"]

PRESET_NAMES = ("paper_dark", "paper_light")


def preset_tokens(name: str = "paper_dark") -> StyleTokens:
    name = (name or "paper_dark").strip().lower()
    if name == "paper_light":
        tokens = style_tokens(
            name="paper_light",
            source="preset",
            background="#f3eee4",
            overlay="#efe7d8",
            panel="#fffaf1",
            panel_light="#ffffff",
            border="#d8cbb7",
            shadow="#7a6a5544",
            accent="#b06a4f",
            accent_soft="#b06a4f33",
            text="#2b2a28",
            text_dim="#5c574f",
            text_muted="#8b8378",
            background_image="",
        )
        tokens.palettes = {
            "read": NodePalette(
                fill="#f6e9db",
                hover="#f1dfcb",
                border="#b06a4f",
                text="#2b2a28",
                strip="#b06a4f",
            ),
            "unread": NodePalette(
                fill="#fffaf1",
                hover="#fdf3e4",
                border="#d8cbb7",
                text="#5c574f",
                strip="#b99372",
            ),
            "locked": NodePalette(
                fill="#ece5d8",
                hover="#ece5d8",
                border="#e0d5c4",
                text="#a29a8c",
                strip="#d8cbb7",
            ),
            "ending": NodePalette(
                fill="#f4e2c8",
                hover="#f0dabd",
                border="#b8893f",
                text="#5a3d17",
                strip="#b8893f",
            ),
            "choice": NodePalette(
                fill="#f8efe2",
                hover="#f3e5d2",
                border="#c68c6d",
                text="#2b2a28",
                strip="#c68c6d",
            ),
            "condition": NodePalette(
                fill="#eef3f2",
                hover="#e6efee",
                border="#8fa9a4",
                text="#3f5652",
                strip="#8fa9a4",
            ),
        }
        tokens.edge = "#c9b9a3"
        tokens.edge_choice = "#b06a4f"
        tokens.edge_condition = "#8fa9a4"
        tokens.edge_call = "#b8a486"
        tokens.button_fill = "#f1e8da"
        tokens.button_hover = "#e9dcc8"
        tokens.button_text = "#2b2a28"
        tokens.close_text = "#5c574f"
        return tokens
    return style_tokens(name="paper_dark", source="preset")
