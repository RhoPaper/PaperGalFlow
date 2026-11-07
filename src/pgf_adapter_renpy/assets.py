"""Generate the nine patch PNG assets used by the flowchart screen.

Ren'Py's ``Frame`` displayable scales an image by keeping its corners and
edges fixed while stretching the middle.  Drawing a small, anti-aliased
rounded rectangle once therefore gives crisp corners at every node size, with
no dependency on the game's own GUI assets (which many commercial builds do
not ship).

Everything here is pure Python: pixels are rendered with a small supersampling
rasteriser and written by :func:`pgf_adapter_renpy.png.encode_png`.
"""

from __future__ import annotations

from dataclasses import dataclass

from pgf_style import StyleTokens, lighten, mix, parse_color

from .png import encode_png

__all__ = ["UiAsset", "UI_DIR", "build_ui_assets", "ui_manifest", "node_frame_border"]

UI_DIR = "pgf_ui"
_SAMPLES = 3
_NODE_SOURCE = 96
_PANEL_SOURCE = 64
_BUTTON_SOURCE = 48
_SWATCH_SIZE = 18

_NODE_STATES = ("read", "unread", "locked", "ending", "choice", "condition")


@dataclass(frozen=True)
class UiAsset:
    name: str
    data: bytes
    role: str = "asset"

    @property
    def byte_size(self) -> int:
        return len(self.data)


def _clamp(value: int, low: int, high: int) -> int:
    return max(low, min(high, int(value)))


def node_frame_border(tokens: StyleTokens) -> int:
    """Nine-patch slice size for nodes (also used by the screen generator)."""

    radius = _clamp(tokens.corner_radius, 0, 22)
    border = _clamp(tokens.border_width, 0, 4)
    return _clamp(radius + border + 8, 20, 34)


def ui_manifest(tokens: StyleTokens) -> dict[str, object]:
    """Paths and slice sizes embedded into the generated screen."""

    frame = node_frame_border(tokens)
    manifest: dict[str, object] = {
        "frame": frame,
        "shadow": f"{UI_DIR}/shadow.png",
        "bar_shadow": f"{UI_DIR}/bar_shadow.png",
        "panel_top": f"{UI_DIR}/panel_top.png",
        "panel_bottom": f"{UI_DIR}/panel_bottom.png",
        "label": f"{UI_DIR}/label.png",
        "button": f"{UI_DIR}/button.png",
        "button_hover": f"{UI_DIR}/button_hover.png",
        "accent_button": f"{UI_DIR}/accent_button.png",
        "accent_button_hover": f"{UI_DIR}/accent_button_hover.png",
    }
    for state in _NODE_STATES:
        manifest[f"node_{state}"] = f"{UI_DIR}/node_{state}.png"
        manifest[f"node_{state}_hover"] = f"{UI_DIR}/node_{state}_hover.png"
        manifest[f"legend_{state}"] = f"{UI_DIR}/legend_{state}.png"
    return manifest


# ---------------------------------------------------------------------------
# raster helpers
# ---------------------------------------------------------------------------


def _rgba(color: str, fallback: tuple[int, int, int, int] = (0, 0, 0, 0)):
    parsed = parse_color(color)
    return parsed if parsed is not None else fallback


def _inside_rounded(
    x: float,
    y: float,
    width: int,
    height: int,
    radii: tuple[int, int, int, int],
) -> bool:
    if x < 0 or y < 0 or x > width or y > height:
        return False
    top_left, top_right, bottom_right, bottom_left = radii
    if top_left and x < top_left and y < top_left:
        return (x - top_left) ** 2 + (y - top_left) ** 2 <= top_left * top_left
    if top_right and x > width - top_right and y < top_right:
        return (x - (width - top_right)) ** 2 + (y - top_right) ** 2 <= top_right * top_right
    if bottom_right and x > width - bottom_right and y > height - bottom_right:
        return (
            (x - (width - bottom_right)) ** 2
            + (y - (height - bottom_right)) ** 2
            <= bottom_right * bottom_right
        )
    if bottom_left and x < bottom_left and y > height - bottom_left:
        return (x - bottom_left) ** 2 + (y - (height - bottom_left)) ** 2 <= bottom_left * bottom_left
    return True


def _coverage(
    x: int,
    y: int,
    width: int,
    height: int,
    radii: tuple[int, int, int, int],
) -> float:
    hits = 0
    samples = _SAMPLES
    for sy in range(samples):
        py = y + (sy + 0.5) / samples
        for sx in range(samples):
            px = x + (sx + 0.5) / samples
            if _inside_rounded(px, py, width, height, radii):
                hits += 1
    return hits / float(samples * samples)


_COVERAGE_CACHE: dict[
    tuple[int, int, tuple[int, int, int, int], int],
    tuple[list[float], list[float]],
] = {}


def _coverage_maps(
    width: int,
    height: int,
    radii: tuple[int, int, int, int],
    border_width: int,
) -> tuple[list[float], list[float]]:
    """Cache per-pixel outer/inner coverage for repeated nine-patch shapes."""

    key = (width, height, radii, border_width)
    cached = _COVERAGE_CACHE.get(key)
    if cached is not None:
        return cached
    border_width = _clamp(border_width, 0, min(width, height) // 2)
    inner_width = max(0, width - 2 * border_width)
    inner_height = max(0, height - 2 * border_width)
    inner_radii = tuple(max(0, radius - border_width) for radius in radii)
    outer_map: list[float] = [0.0] * (width * height)
    inner_map: list[float] = [0.0] * (width * height)
    for y in range(height):
        row = y * width
        for x in range(width):
            outer = _coverage(x, y, width, height, radii)
            outer_map[row + x] = outer
            if outer <= 0:
                continue
            if border_width:
                inner = _coverage(
                    x - border_width,
                    y - border_width,
                    inner_width,
                    inner_height,
                    inner_radii,
                )
                inner_map[row + x] = min(inner, outer)
            else:
                inner_map[row + x] = outer
    _COVERAGE_CACHE[key] = (outer_map, inner_map)
    return outer_map, inner_map


def _blend_over(
    dst: list[int],
    index: int,
    color: tuple[int, int, int, int],
    coverage: float,
) -> None:
    """Source-over composite one straight-alpha colour onto ``dst``."""

    if coverage <= 0:
        return
    source_alpha = (color[3] / 255.0) * coverage
    if source_alpha <= 0:
        return
    dest_alpha = dst[index + 3] / 255.0
    out_alpha = source_alpha + dest_alpha * (1.0 - source_alpha)
    if out_alpha <= 0:
        return
    for channel in range(3):
        src = color[channel] / 255.0
        dest = dst[index + channel] / 255.0
        value = (src * source_alpha + dest * dest_alpha * (1.0 - source_alpha)) / out_alpha
        dst[index + channel] = _clamp(int(round(value * 255)), 0, 255)
    dst[index + 3] = _clamp(int(round(out_alpha * 255)), 0, 255)


def _rounded_patch(
    width: int,
    height: int,
    radii: tuple[int, int, int, int],
    fill: str,
    border: str,
    border_width: int,
) -> bytearray:
    """Render an opaque rounded rectangle, optionally with a border."""

    fill_rgba = _rgba(fill, (0, 0, 0, 255))
    border_rgba = _rgba(border, fill_rgba)
    border_width = _clamp(border_width, 0, min(width, height) // 2)
    outer_map, inner_map = _coverage_maps(width, height, radii, border_width)

    pixels = bytearray(width * height * 4)
    for y in range(height):
        row = y * width * 4
        for x in range(width):
            index = row + x * 4
            outer = outer_map[y * width + x]
            if outer <= 0:
                continue
            inner = inner_map[y * width + x]
            # Treat the border and fill as one opaque surface: the pixel keeps
            # the outer coverage and mixes the two colours by inner coverage.
            # Compositing them separately would leave a translucent seam at
            # the anti-aliased inner edge.
            fill_weight = inner / outer if outer else 0.0
            border_weight = 1.0 - fill_weight
            alpha = int(round(outer * 255))
            for channel in range(3):
                value = (
                    fill_rgba[channel] * fill_weight
                    + border_rgba[channel] * border_weight
                )
                pixels[index + channel] = _clamp(int(round(value)), 0, 255)
            pixels[index + 3] = alpha
    return pixels


def _composite_rounded(
    pixels: bytearray,
    width: int,
    height: int,
    rect: tuple[int, int, int, int],
    radius: int,
    color: str,
) -> None:
    """Alpha-composite a small rounded rectangle onto an existing image."""

    left, top, rect_w, rect_h = rect
    rgba = _rgba(color)
    radii = (radius, radius, radius, radius)
    for y in range(rect_h):
        target_y = top + y
        if target_y < 0 or target_y >= height:
            continue
        for x in range(rect_w):
            target_x = left + x
            if target_x < 0 or target_x >= width:
                continue
            coverage = _coverage(x, y, rect_w, rect_h, radii)
            if coverage <= 0:
                continue
            _blend_over(pixels, (target_y * width + target_x) * 4, rgba, coverage)


def _blur(mask: list[float], width: int, height: int, radius: int) -> list[float]:
    """Separable box blur, applied twice for a soft Gaussian-ish falloff."""

    if radius <= 0:
        return list(mask)
    current = list(mask)
    for _pass in range(2):
        horizontal = [0.0] * len(current)
        for y in range(height):
            row = y * width
            for x in range(width):
                total = 0.0
                count = 0
                for offset in range(-radius, radius + 1):
                    nx = x + offset
                    if 0 <= nx < width:
                        total += current[row + nx]
                        count += 1
                horizontal[row + x] = total / count
        vertical = [0.0] * len(current)
        for y in range(height):
            for x in range(width):
                total = 0.0
                count = 0
                for offset in range(-radius, radius + 1):
                    ny = y + offset
                    if 0 <= ny < height:
                        total += horizontal[ny * width + x]
                        count += 1
                vertical[y * width + x] = total / count
        current = vertical
    return current


def _shadow_pixels(tokens: StyleTokens) -> bytearray:
    size = _NODE_SOURCE
    inset = 14
    radius = _clamp(tokens.corner_radius, 4, 20)
    mask = [0.0] * (size * size)
    for y in range(inset, size - inset):
        for x in range(inset, size - inset):
            coverage = _coverage(
                x - inset,
                y - inset,
                size - 2 * inset,
                size - 2 * inset,
                (radius, radius, radius, radius),
            )
            if coverage:
                mask[y * size + x] = coverage
    mask = _blur(mask, size, size, 8)
    rgba = _rgba(tokens.shadow, (0, 0, 0, 90))
    strength = max(0.0, min(1.0, rgba[3] / 255.0)) * 0.9
    pixels = bytearray(size * size * 4)
    for index, value in enumerate(mask):
        alpha = value * strength
        if alpha <= 0:
            continue
        base = index * 4
        pixels[base] = rgba[0]
        pixels[base + 1] = rgba[1]
        pixels[base + 2] = rgba[2]
        pixels[base + 3] = _clamp(int(round(alpha * 255)), 0, 255)
    return pixels


def _bar_shadow_pixels(tokens: StyleTokens) -> bytearray:
    width, height = 128, 28
    rgba = _rgba(tokens.shadow, (0, 0, 0, 90))
    strength = max(0.0, min(1.0, rgba[3] / 255.0)) * 0.85
    pixels = bytearray(width * height * 4)
    for y in range(height):
        fade = (1.0 - y / float(height - 1)) ** 1.7
        alpha = int(round(255 * strength * fade))
        for x in range(width):
            # Soften the two ends so the strip does not end in a hard corner.
            edge = min(1.0, (x + 1) / 18.0, (width - x) / 18.0)
            index = (y * width + x) * 4
            pixels[index] = rgba[0]
            pixels[index + 1] = rgba[1]
            pixels[index + 2] = rgba[2]
            pixels[index + 3] = int(round(alpha * edge))
    return pixels


# ---------------------------------------------------------------------------
# public generator
# ---------------------------------------------------------------------------


def build_ui_assets(tokens: StyleTokens) -> list[UiAsset]:
    """Return every generated UI PNG, in a stable order."""

    assets: list[UiAsset] = []
    radius = _clamp(tokens.corner_radius, 0, 22)
    border_width = _clamp(tokens.border_width, 0, 4)
    node_border = node_frame_border(tokens)
    metadata = {"Comment": f"PaperGalFlow generated nine-patch ({tokens.name})"}

    for state in _NODE_STATES:
        palette = tokens.palette(state)
        for hover, fill in ((False, palette.fill), (True, palette.hover)):
            pixels = _rounded_patch(
                _NODE_SOURCE,
                _NODE_SOURCE,
                (radius, radius, radius, radius),
                fill,
                palette.border,
                border_width,
            )
            if radius:
                strip_top = max(radius, 16)
                strip_height = max(8, _NODE_SOURCE - 2 * strip_top)
                _composite_rounded(
                    pixels,
                    _NODE_SOURCE,
                    _NODE_SOURCE,
                    (10, strip_top, 6, strip_height),
                    3,
                    palette.strip,
                )
            suffix = "_hover" if hover else ""
            assets.append(
                UiAsset(
                    f"{UI_DIR}/node_{state}{suffix}.png",
                    encode_png(_NODE_SOURCE, _NODE_SOURCE, bytes(pixels), metadata=metadata),
                )
            )

    for state in ("read", "unread", "locked", "ending"):
        palette = tokens.palette(state)
        pixels = _rounded_patch(
            _SWATCH_SIZE,
            _SWATCH_SIZE,
            (4, 4, 4, 4),
            palette.strip,
            palette.strip,
            0,
        )
        assets.append(
            UiAsset(
                f"{UI_DIR}/legend_{state}.png",
                encode_png(_SWATCH_SIZE, _SWATCH_SIZE, bytes(pixels), metadata=metadata),
            )
        )

    assets.append(
        UiAsset(
            f"{UI_DIR}/shadow.png",
            encode_png(_NODE_SOURCE, _NODE_SOURCE, bytes(_shadow_pixels(tokens)), metadata=metadata),
        )
    )
    assets.append(
        UiAsset(
            f"{UI_DIR}/bar_shadow.png",
            encode_png(128, 28, bytes(_bar_shadow_pixels(tokens)), metadata=metadata),
        )
    )

    panel_radius = min(radius, 18)
    for name, corners in (
        ("panel_top", (0, 0, panel_radius, panel_radius)),
        ("panel_bottom", (panel_radius, panel_radius, 0, 0)),
    ):
        pixels = _rounded_patch(
            _PANEL_SOURCE,
            _PANEL_SOURCE,
            corners,
            tokens.panel,
            tokens.border,
            1,
        )
        assets.append(
            UiAsset(
                f"{UI_DIR}/{name}.png",
                encode_png(_PANEL_SOURCE, _PANEL_SOURCE, bytes(pixels), metadata=metadata),
            )
        )

    label_radius = min(10, radius or 10)
    pixels = _rounded_patch(
        _BUTTON_SOURCE,
        _BUTTON_SOURCE,
        (label_radius, label_radius, label_radius, label_radius),
        tokens.panel,
        mix(tokens.border, tokens.accent, 0.25),
        1,
    )
    assets.append(
        UiAsset(
            f"{UI_DIR}/label.png",
            encode_png(_BUTTON_SOURCE, _BUTTON_SOURCE, bytes(pixels), metadata=metadata),
        )
    )

    button_radius = min(10, radius or 10)
    for name, fill in (("button", tokens.button_fill), ("button_hover", tokens.button_hover)):
        pixels = _rounded_patch(
            _BUTTON_SOURCE,
            _BUTTON_SOURCE,
            (button_radius, button_radius, button_radius, button_radius),
            fill,
            tokens.border,
            1,
        )
        assets.append(
            UiAsset(
                f"{UI_DIR}/{name}.png",
                encode_png(_BUTTON_SOURCE, _BUTTON_SOURCE, bytes(pixels), metadata=metadata),
            )
        )

    accent_radius = min(14, radius or 14)
    for name, fill in (
        ("accent_button", tokens.accent),
        ("accent_button_hover", lighten(tokens.accent, 0.16)),
    ):
        pixels = _rounded_patch(
            _PANEL_SOURCE,
            _PANEL_SOURCE,
            (accent_radius, accent_radius, accent_radius, accent_radius),
            fill,
            fill,
            0,
        )
        assets.append(
            UiAsset(
                f"{UI_DIR}/{name}.png",
                encode_png(_PANEL_SOURCE, _PANEL_SOURCE, bytes(pixels), metadata=metadata),
            )
        )
    return assets
