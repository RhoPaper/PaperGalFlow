"""Style tokens: the engine independent description of how the chart looks."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any, Mapping

from .colors import contrast_text, luminance, normalize_color

__all__ = ["NodePalette", "StyleTokens", "style_tokens"]


@dataclass(frozen=True)
class NodePalette:
    """Colours for one node state or node kind."""

    fill: str
    border: str
    text: str
    strip: str
    hover: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "hover", self.hover or self.fill)

    def to_dict(self) -> dict[str, str]:
        return {
            "fill": self.fill,
            "border": self.border,
            "text": self.text,
            "strip": self.strip,
            "hover": self.hover,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, str]) -> "NodePalette":
        return cls(
            fill=str(data.get("fill", "#000000")),
            border=str(data.get("border", "#000000")),
            text=str(data.get("text", "#ffffff")),
            strip=str(data.get("strip", "#000000")),
            hover=str(data.get("hover", "")),
        )


@dataclass
class StyleTokens:
    """Colours, typography and spacing for the flowchart screen."""

    name: str = "paper_dark"
    source: str = "preset"
    confidence: float = 0.0
    notes: list[str] = field(default_factory=list)

    # typography
    font: str = ""
    font_bold: str = ""
    title_size: int = 44
    node_text_size: int = 23
    subtitle_size: int = 16
    edge_text_size: int = 18
    legend_size: int = 20
    hint_size: int = 17

    # layout
    node_width: int = 260
    node_height: int = 92
    node_padding: int = 15
    panel_padding: int = 18
    margin: int = 24

    # nine patch geometry (rendered into generated PNG assets)
    corner_radius: int = 16
    border_width: int = 2

    # surfaces
    background: str = "#0b0f16"
    overlay: str = "#05080d"
    panel: str = "#141b25"
    panel_light: str = "#1c2532"
    border: str = "#2c3a4d"
    shadow: str = "#00000099"
    accent: str = "#8fb8ff"
    accent_soft: str = "#8fb8ff33"
    text: str = "#eef3fa"
    text_dim: str = "#a9b6c9"
    text_muted: str = "#71809a"
    background_image: str = ""

    # node palettes keyed by runtime state / node kind
    palettes: dict[str, NodePalette] = field(default_factory=dict)

    # edge colours
    edge: str = "#3c4d63"
    edge_choice: str = "#7fa2cc"
    edge_condition: str = "#4f748c"
    edge_call: str = "#8a7a5a"

    # chrome
    button_fill: str = "#1c2532"
    button_hover: str = "#263244"
    button_text: str = "#e6eef9"
    close_text: str = "#c7d3e4"

    def __post_init__(self) -> None:
        self.name = str(self.name)
        self.notes = [str(note) for note in self.notes]
        self.confidence = max(0.0, min(1.0, float(self.confidence)))
        if not self.palettes:
            self.palettes = default_palettes(self)
        else:
            self.palettes = {
                str(key): value if isinstance(value, NodePalette) else NodePalette.from_dict(value)
                for key, value in self.palettes.items()
            }
            for key, palette in default_palettes(self).items():
                self.palettes.setdefault(key, palette)

    # -- helpers -------------------------------------------------------------
    def palette(self, state: str) -> NodePalette:
        return self.palettes.get(state) or self.palettes["unread"]

    def merged(self, **changes: Any) -> "StyleTokens":
        return replace(self, **changes)

    def to_dict(self) -> dict[str, Any]:
        data = {
            key: value
            for key, value in self.__dict__.items()
            if key not in ("palettes",)
        }
        data["palettes"] = {key: palette.to_dict() for key, palette in self.palettes.items()}
        return data

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "StyleTokens":
        fields = set(cls.__dataclass_fields__)
        payload = {key: value for key, value in data.items() if key in fields}
        payload["palettes"] = {
            str(key): NodePalette.from_dict(value)
            for key, value in dict(data.get("palettes", {})).items()
        }
        return cls(**payload)


def default_palettes(tokens: StyleTokens) -> dict[str, NodePalette]:
    """Derive the six palettes from the token's base colours.

    Explicitly passed palettes win; this only fills the gap.
    """

    accent = tokens.accent
    panel = tokens.panel
    border = tokens.border
    text = tokens.text
    dim = tokens.text_dim
    muted = tokens.text_muted
    from .colors import darken, lighten, mix  # local import to avoid cycle

    return {
        "read": NodePalette(
            fill=mix(panel, accent, 0.16),
            hover=mix(panel, accent, 0.26),
            border=accent,
            text=tokens.text,
            strip=accent,
        ),
        "unread": NodePalette(
            fill=panel,
            hover=lighten(panel, 0.06),
            border=mix(border, accent, 0.25),
            text=dim,
            strip=mix(accent, border, 0.55),
        ),
        "locked": NodePalette(
            fill=darken(panel, 0.25),
            hover=darken(panel, 0.25),
            border=darken(border, 0.35),
            text=muted,
            strip=darken(border, 0.2),
        ),
        "ending": NodePalette(
            fill=mix(panel, "#d9b36a", 0.20),
            hover=mix(panel, "#d9b36a", 0.28),
            border="#c39a52" if luminance(panel) > 0.45 else "#d9b36a",
            text=contrast_text(mix(panel, "#d9b36a", 0.20), "#f6e2b3", "#4a3413"),
            strip="#d9b36a",
        ),
        "choice": NodePalette(
            fill=mix(panel, accent, 0.10),
            hover=mix(panel, accent, 0.18),
            border=mix(accent, border, 0.35),
            text=lighten(text, 0.06),
            strip=mix(accent, border, 0.25),
        ),
        "condition": NodePalette(
            fill=mix(panel, "#6f9bb3", 0.10),
            hover=mix(panel, "#6f9bb3", 0.17),
            border=mix("#6f9bb3", border, 0.4),
            text=dim,
            strip="#6f9bb3",
        ),
    }


def style_tokens(**overrides: Any) -> StyleTokens:
    """Build tokens, normalising colour strings and integer sizes."""

    tokens = StyleTokens(**overrides)
    for attribute in (
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
    ):
        current = getattr(tokens, attribute)
        normalized = normalize_color(current)
        if normalized:
            setattr(tokens, attribute, normalized)
    for attribute in (
        "title_size",
        "node_text_size",
        "subtitle_size",
        "edge_text_size",
        "legend_size",
        "hint_size",
        "node_width",
        "node_height",
    ):
        setattr(tokens, attribute, max(8, int(getattr(tokens, attribute))))
    for attribute in ("corner_radius", "border_width"):
        setattr(tokens, attribute, max(0, int(getattr(tokens, attribute))))
    tokens.palettes = {
        key: NodePalette(
            fill=normalize_color(palette.fill, tokens.panel),
            border=normalize_color(palette.border, tokens.border),
            text=normalize_color(palette.text, tokens.text),
            strip=normalize_color(palette.strip, tokens.accent),
            hover=normalize_color(palette.hover, ""),
        )
        for key, palette in tokens.palettes.items()
    }
    return tokens
