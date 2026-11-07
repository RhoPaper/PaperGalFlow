"""Turn adapter style evidence into style tokens.

Degradation happens in three layers:

1. explicit GUI values (``gui.accent_color``, fonts, sizes) -- highest trust,
2. colours sampled from the game's own UI assets,
3. the built in preset palette -- always available.

Missing pieces fall through independently, so a game with a custom font but no
usable colour declarations still gets its font.
"""

from __future__ import annotations

from typing import Iterable

from .colors import (
    contrast_ratio,
    darken,
    lighten,
    luminance,
    mix,
    normalize_color,
    with_alpha,
)
from .evidence import StyleEvidence, UiSample
from .presets import preset_tokens
from .tokens import NodePalette, StyleTokens, default_palettes

__all__ = ["tokens_from_evidence", "resolve_ui_samples"]

_COLOR_ROLES = (
    "accent",
    "idle",
    "hover",
    "selected",
    "text",
    "interface_text",
    "muted",
    "locked",
)


def _sample(evidence: StyleEvidence, *names: str) -> UiSample | None:
    for sample in evidence.ui_samples:
        if sample.name in names:
            return sample
    return None


def _color_from_samples(evidence: StyleEvidence, *names: str) -> str:
    sample = _sample(evidence, *names)
    if sample is None:
        return ""
    return normalize_color(sample.color) or normalize_color(sample.average)


def _center_from_samples(evidence: StyleEvidence, *names: str) -> str:
    sample = _sample(evidence, *names)
    if sample is None:
        return ""
    return (
        normalize_color(sample.center)
        or normalize_color(sample.color)
        or normalize_color(sample.average)
    )


def resolve_ui_samples(samples: Iterable[UiSample]) -> dict[str, str]:
    """Return the best colour per semantic name from raw samples."""

    result: dict[str, str] = {}
    for sample in samples:
        color = normalize_color(sample.color) or normalize_color(sample.average)
        if color:
            result.setdefault(sample.name, color)
    return result


def tokens_from_evidence(
    evidence: StyleEvidence | None,
    preset: str = "paper_dark",
) -> StyleTokens:
    """Blend evidence over a preset and return the final tokens."""

    if evidence is None:
        tokens = preset_tokens(preset)
        tokens.source = "preset"
        tokens.notes = ["no style evidence; using the built-in preset"]
        return tokens

    accent = normalize_color(evidence.colors.get("accent", "")) or _color_from_samples(
        evidence, "accent", "quick_icon", "quick_button"
    )
    panel_sample = _sample(evidence, "panel", "option_bg", "dialog_bg", "menu_bg")
    panel = normalize_color(evidence.colors.get("panel", "")) or _center_from_samples(
        evidence, "panel", "option_bg", "dialog_bg", "menu_bg"
    )

    chosen_preset = preset
    if panel and luminance(panel) > 0.62:
        chosen_preset = "paper_light"
    elif not panel and normalize_color(evidence.colors.get("text", "")):
        text_guess = normalize_color(evidence.colors.get("text", ""))
        if text_guess and luminance(text_guess) < 0.35:
            # Dark text usually means a light UI, but without a sampled panel
            # we cannot be sure; stay on the dark overlay for readability.
            pass

    tokens = preset_tokens(chosen_preset)
    tokens.name = "evidence_" + chosen_preset
    applied: list[str] = []
    surface_notes: list[str] = []

    if panel:
        tokens.panel = panel
        tokens.panel_light = lighten(panel, 0.07)
        if luminance(panel) > 0.55:
            tokens.background = lighten(panel, 0.30)
            tokens.overlay = with_alpha(darken(panel, 0.55), 0.10)
            tokens.shadow = with_alpha(darken(panel, 0.65), 0.16)
        else:
            tokens.background = darken(panel, 0.65)
            tokens.overlay = with_alpha("#000000", 0.28)
            tokens.shadow = with_alpha("#000000", 0.35)
        tokens.border = mix(panel, tokens.text_dim, 0.55)
        applied.append("panel")

    if panel_sample is not None:
        edge = normalize_color(panel_sample.edge)
        if edge and contrast_ratio(edge, tokens.panel) >= 1.15:
            tokens.border = edge
            applied.append("panel_border")
        if panel_sample.corner_radius:
            tokens.corner_radius = max(6, min(24, int(panel_sample.corner_radius)))
            applied.append("corner_radius")
        if panel_sample.border_width:
            tokens.border_width = max(1, min(4, int(panel_sample.border_width)))
        if panel_sample.insets:
            surface_notes.append(
                "nine-patch insets "
                + ",".join(str(value) for value in panel_sample.insets)
            )
        if panel_sample.gradient:
            surface_notes.append(
                "gradient panel "
                f"{panel_sample.gradient_top} -> {panel_sample.gradient_bottom}; "
                f"sampled centre {tokens.panel}"
            )
        if panel_sample.coverage < 0.98 or panel_sample.opacity < 0.98:
            surface_notes.append(
                f"translucent panel (coverage {panel_sample.coverage:.2f}, "
                f"average alpha {panel_sample.opacity:.2f})"
            )

    text = normalize_color(evidence.colors.get("text", ""))
    if text and contrast_ratio(text, tokens.panel) >= 3.0:
        tokens.text = text
        applied.append("text")
    elif chosen_preset == "paper_dark":
        tokens.text = "#eef3fa"

    interface_text = normalize_color(evidence.colors.get("interface_text", ""))
    if interface_text and contrast_ratio(interface_text, tokens.panel) >= 3.0:
        if luminance(tokens.panel) > 0.55:
            tokens.text_dim = mix(interface_text, tokens.panel, 0.28)
        else:
            tokens.text_dim = mix(interface_text, tokens.text, 0.35)
        applied.append("interface_text")

    tokens.text_muted = mix(tokens.text_dim, tokens.panel, 0.45)

    if accent:
        if contrast_ratio(accent, tokens.panel) < 2.2:
            accent = darken(accent, 0.4) if luminance(tokens.panel) > 0.5 else lighten(accent, 0.45)
        tokens.accent = accent
        tokens.accent_soft = with_alpha(accent, 0.22)
        applied.append("accent")

    font = str(evidence.fonts.get("text") or evidence.fonts.get("interface") or "").strip()
    if font:
        tokens.font = font
        tokens.font_bold = str(evidence.fonts.get("name") or font).strip()
        applied.append("font")

    text_size = evidence.sizes.get("interface_text") or evidence.sizes.get("text")
    if text_size:
        tokens.node_text_size = max(18, min(30, int(round(text_size * 0.72))))
        tokens.subtitle_size = max(14, min(20, int(round(text_size * 0.5))))
        tokens.edge_text_size = max(14, min(21, int(round(text_size * 0.56))))
        tokens.legend_size = max(16, min(24, int(round(text_size * 0.6))))
        tokens.hint_size = max(14, min(20, int(round(text_size * 0.52))))
        applied.append("text_size")
    title_size = evidence.sizes.get("title")
    if title_size:
        tokens.title_size = max(32, min(56, int(round(title_size * 0.6))))
        applied.append("title_size")

    if evidence.background_image:
        tokens.background_image = evidence.background_image

    # Rebuild the palettes from the (possibly changed) base colours.
    tokens.palettes = default_palettes(tokens)
    if chosen_preset == "paper_light":
        tokens.palettes.update(
            {
                "read": NodePalette(
                    fill=mix(tokens.panel, tokens.accent, 0.30),
                    hover=mix(tokens.panel, tokens.accent, 0.42),
                    border=tokens.accent,
                    text=tokens.text,
                    strip=tokens.accent,
                ),
                "unread": NodePalette(
                    fill=tokens.panel_light,
                    hover=lighten(tokens.panel, 0.02),
                    border=mix(tokens.border, tokens.accent, 0.35),
                    text=tokens.text_dim,
                    strip=mix(tokens.accent, tokens.border, 0.55),
                ),
                "locked": NodePalette(
                    fill=mix(tokens.panel, "#8a8a8a", 0.14),
                    hover=mix(tokens.panel, "#8a8a8a", 0.14),
                    border=lighten(tokens.border, 0.18),
                    text=tokens.text_muted,
                    strip=lighten(tokens.border, 0.05),
                ),
            }
        )

    tokens.edge = mix(tokens.text_dim, tokens.text, 0.35)
    tokens.edge_choice = mix(tokens.accent, tokens.text, 0.18)
    tokens.edge_condition = mix(tokens.border, "#6f9bb3", 0.45)
    tokens.edge_call = mix(tokens.border, "#b39a6a", 0.55)
    tokens.button_fill = mix(tokens.panel, tokens.accent, 0.16)
    tokens.button_hover = mix(tokens.panel, tokens.accent, 0.32)
    tokens.button_text = tokens.text
    tokens.close_text = tokens.text_dim

    tokens.source = "game+assets" if evidence.ui_samples else ("game" if applied else "preset")
    tokens.confidence = min(1.0, len(applied) / 6.0 + (0.2 if evidence.ui_samples else 0.0))
    tokens.notes = list(evidence.sources)
    if applied:
        tokens.notes.append("applied: " + ", ".join(applied))
    tokens.notes.extend(surface_notes)
    for warning in evidence.warnings:
        tokens.notes.append("warning: " + warning)
    return tokens
