"""Evidence produced by an adapter's UI probing pass.

The adapter knows how to read a game's GUI files and assets; this module
defines the engine independent shape of what it hands back.  The style layer
turns evidence into :class:`~pgf_style.tokens.StyleTokens`.
"""

from __future__ import annotations

from dataclasses import dataclass, field

__all__ = ["UiSample", "StyleEvidence"]


@dataclass
class UiSample:
    """One sampled UI asset (an averaged/dominant colour plus metadata)."""

    name: str
    path: str = ""
    color: str = ""
    average: str = ""
    alpha: float = 1.0
    width: int = 0
    height: int = 0

    def to_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "path": self.path,
            "color": self.color,
            "average": self.average,
            "alpha": round(self.alpha, 3),
            "width": self.width,
            "height": self.height,
        }


@dataclass
class StyleEvidence:
    """Everything an adapter managed to learn about a game's visual style."""

    colors: dict[str, str] = field(default_factory=dict)
    fonts: dict[str, str] = field(default_factory=dict)
    sizes: dict[str, int] = field(default_factory=dict)
    screen_size: tuple[int, int] | None = None
    background_image: str = ""
    ui_samples: list[UiSample] = field(default_factory=list)
    sources: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def confidence(self) -> float:
        """Rough 0..1 score used to pick how much evidence to trust."""

        checks = 0
        hits = 0
        checks += 1
        hits += 1 if self.colors.get("accent") else 0
        checks += 1
        hits += 1 if self.fonts.get("text") else 0
        checks += 1
        hits += 1 if self.sizes.get("interface_text") else 0
        checks += 1
        hits += 1 if self.screen_size else 0
        checks += 1
        hits += 1 if self.ui_samples else 0
        return hits / checks

    def summary(self) -> dict[str, object]:
        return {
            "colors": len(self.colors),
            "fonts": len(self.fonts),
            "sizes": len(self.sizes),
            "samples": len(self.ui_samples),
            "screen_size": list(self.screen_size) if self.screen_size else None,
            "confidence": round(self.confidence(), 2),
        }
