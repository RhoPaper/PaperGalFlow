"""Probe a Ren'Py game's GUI for style evidence.

The probe is deliberately defensive: every source of evidence is optional and a
failure only produces a warning.  It reads ``gui.*`` define statements, style
blocks and screen language trees, then samples the game's own PNG assets (as
stored in ``.rpa`` archives) for authentic colours.
"""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass, field
from typing import Iterable

from pgf_core.errors import PgfError
from pgf_style import StyleEvidence, UiSample, luminance as _luminance, lighten as _lighten, normalize_color

from .archive import ArchiveError, GameArchive
from .png import PngError, color_stats, png_size
from .script_model import ScreenElement, ScreenInfo, ScriptFile

__all__ = [
    "QuickButton",
    "QuickMenuProbe",
    "StyleProbeResult",
    "probe_style",
]

_SCREEN_INIT_RE = re.compile(r"gui\.init\s*\(\s*(\d+)\s*,\s*(\d+)\s*\)")
_IMAGE_PATH_RE = re.compile(r"""["']([^"']+\.(?:png|jpe?g|webp))["']""", re.I)
_GUI_REF_RE = re.compile(r"^(?:gui\.)?([A-Za-z_][\w]*)$")

_COLOR_KEYS = {
    "accent": ("accent_color", "hover_color"),
    "idle": ("idle_color", "idle_small_color"),
    "hover": ("hover_color",),
    "selected": ("selected_color",),
    "text": ("text_color",),
    "interface_text": ("interface_text_color",),
    "muted": ("muted_color", "insensitive_color"),
}
_FONT_KEYS = {
    "text": ("text_font",),
    "name": ("name_text_font",),
    "interface": ("interface_text_font",),
}
_SIZE_KEYS = {
    "text": "text_size",
    "interface_text": "interface_text_size",
    "title": "title_text_size",
    "label": "label_text_size",
    "quick_button": "quick_button_text_size",
}


@dataclass
class QuickButton:
    x: int = 0
    y: int = 0
    width: int = 0
    height: int = 0
    asset: str = ""


@dataclass
class QuickMenuProbe:
    """What we learned about the game's quick menu."""

    screen_name: str = "quick_menu"
    found: bool = False
    has_source: bool = False
    source: str = ""
    buttons: list[QuickButton] = field(default_factory=list)
    screen_size: tuple[int, int] | None = None
    used_by_say: bool = False
    assets: list[str] = field(default_factory=list)

    @property
    def button_count(self) -> int:
        return len(self.buttons)

    def row_buttons(self) -> list[QuickButton]:
        """Buttons belonging to the densest horizontal row."""

        positioned = [button for button in self.buttons if button.x or button.y]
        if not positioned:
            return []
        buckets: list[list[QuickButton]] = []
        for button in sorted(positioned, key=lambda b: (b.y, b.x)):
            for bucket in buckets:
                if abs(bucket[0].y - button.y) <= 60:
                    bucket.append(button)
                    break
            else:
                buckets.append([button])
        return max(buckets, key=len)

    @property
    def bbox(self) -> tuple[int, int, int, int] | None:
        positioned = self.row_buttons()
        if not positioned:
            return None
        left = min(button.x for button in positioned)
        top = min(button.y for button in positioned)
        right = max(button.x + max(button.width, 120) for button in positioned)
        bottom = max(button.y + max(button.height, 56) for button in positioned)
        return left, top, right, bottom

    def placement(
        self,
        width: int,
        height: int,
        *,
        gap: int = 18,
        margin: int = 16,
    ) -> tuple[int, int]:
        """Pick a free spot next to the original quick menu buttons."""

        screen_width, screen_height = self.screen_size or (1920, 1080)
        bbox = self.bbox
        if bbox is None:
            return (screen_width - width - margin * 2, screen_height - height - margin * 4)
        left, top, right, bottom = bbox
        centre_y = top + (bottom - top - height) // 2
        if right + gap + width <= screen_width - margin:
            return (right + gap, max(margin, centre_y))
        if left - gap - width >= margin:
            return (left - gap - width, max(margin, centre_y))
        if bottom + gap + height <= screen_height - margin:
            return (left, bottom + gap)
        if top - gap - height >= margin:
            return (left, top - gap - height)
        return (screen_width - width - margin, screen_height - height - margin * 4)


@dataclass
class StyleProbeResult:
    evidence: StyleEvidence = field(default_factory=StyleEvidence)
    quick_menu: QuickMenuProbe | None = None
    warnings: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def summary(self) -> dict[str, object]:
        return {
            "evidence": self.evidence.summary(),
            "quick_menu": {
                "found": bool(self.quick_menu and self.quick_menu.found),
                "buttons": self.quick_menu.button_count if self.quick_menu else 0,
                "has_source": bool(self.quick_menu and self.quick_menu.has_source),
                "bbox": list(self.quick_menu.bbox) if self.quick_menu and self.quick_menu.bbox else None,
            },
            "warnings": len(self.warnings),
        }


# ---------------------------------------------------------------------------
# value resolution
# ---------------------------------------------------------------------------


def _resolve(raw: str, defines: dict[str, str], depth: int = 0) -> object:
    if depth > 8 or raw is None:
        return raw
    text = str(raw).strip()
    if not text:
        return ""
    try:
        value = ast.literal_eval(text)
    except (ValueError, SyntaxError):
        value = None
    if isinstance(value, (str, int, float, bool)):
        return value
    match = _GUI_REF_RE.match(text)
    if match:
        key = match.group(1)
        if key in defines:
            return _resolve(defines[key], defines, depth + 1)
    return text


def _resolve_str(raw: str, defines: dict[str, str]) -> str:
    value = _resolve(raw, defines)
    if value is None:
        return ""
    if isinstance(value, bool):
        return ""
    return str(value).strip()


def _resolve_int(raw: str, defines: dict[str, str]) -> int | None:
    value = _resolve(raw, defines)
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    text = str(value).strip()
    if re.fullmatch(r"-?\d+", text):
        return int(text)
    try:
        number = float(text)
    except ValueError:
        return None
    return int(number) if number.is_integer() else None


_ICON_HINTS = ("skip", "logo", "title", "icon", "arrow", "thumb", "gallery", "slider", "bar_")
_PANEL_HINTS = ("dialog_bg", "option", "choice", "textbox", "game_menu", "frame", "panel")


def _classify_asset(path: str, context: str = "") -> str:
    lowered = (path + " " + context).lower()
    if "dialog_bg" in lowered or "textbox" in lowered:
        return "dialog_bg"
    if "option" in lowered or "choice" in lowered:
        if any(word in lowered for word in ("click", "hover", "selected")):
            return "option_bg_hover"
        return "option_bg"
    if "game_menu" in lowered:
        return "menu_bg"
    if "quick" in context.lower() or "menu_" in path.lower():
        if any(word in lowered for word in ("click", "hover", "selected")):
            return "quick_icon_hover"
        return "quick_icon"
    if any(hint in path.lower() for hint in _ICON_HINTS):
        return "asset"
    if any(hint in lowered for hint in _PANEL_HINTS):
        return "dialog_bg"
    return "asset"


def _usable_panel_asset(path: str) -> bool:
    lowered = path.lower()
    if any(hint in lowered for hint in _ICON_HINTS):
        return False
    return any(hint in lowered for hint in _PANEL_HINTS)


def _image_path(raw: str) -> str:
    match = _IMAGE_PATH_RE.search(str(raw))
    if match:
        return match.group(1)
    text = str(raw).strip().strip("'\"")
    if text.lower().endswith((".png", ".jpg", ".jpeg", ".webp")):
        return text
    return ""


def _find_screen_size(scripts: Iterable[ScriptFile], defines: dict[str, str]) -> tuple[int, int] | None:
    for script in scripts:
        for statement in script.statements:
            for node in statement.walk():
                source = node.source or ""
                if "gui.init" in source:
                    match = _SCREEN_INIT_RE.search(source)
                    if match:
                        return int(match.group(1)), int(match.group(2))
    width = _resolve_int(defines.get("screen_width", ""), defines)
    height = _resolve_int(defines.get("screen_height", ""), defines)
    if width and height:
        return width, height
    return None


def _collect_styles(scripts: Iterable[ScriptFile]) -> dict[str, dict[str, str]]:
    styles: dict[str, dict[str, str]] = {}
    for script in scripts:
        for name, properties in script.styles().items():
            styles.setdefault(name, {}).update(properties)
    return styles


def _find_quick_menu(
    scripts: Iterable[ScriptFile],
    defines: dict[str, str],
    screen_size: tuple[int, int] | None,
) -> QuickMenuProbe | None:
    scripts = list(scripts)
    screens: dict[str, tuple[ScreenInfo, ScriptFile]] = {}
    used_by_say = False
    for script in scripts:
        for name, info in script.screens().items():
            screens.setdefault(name, (info, script))
    for script in scripts:
        for info in script.screens().values():
            if info.uses("quick_menu"):
                used_by_say = True

    chosen: tuple[str, ScreenInfo, ScriptFile] | None = None
    if "quick_menu" in screens:
        info, script = screens["quick_menu"]
        chosen = ("quick_menu", info, script)
    else:
        for name, (info, script) in screens.items():
            if "quick" in name.lower():
                chosen = (name, info, script)
                break
    if chosen is None:
        return QuickMenuProbe(found=False, used_by_say=used_by_say, screen_size=screen_size)

    name, info, _script = chosen
    probe = QuickMenuProbe(
        screen_name=name,
        found=True,
        has_source=bool(info.source),
        source=info.source,
        screen_size=screen_size,
        used_by_say=used_by_say,
    )
    for element in info.walk():
        if element.kind not in ("imagebutton", "button", "textbutton"):
            continue
        x = _resolve_int(element.prop("xpos"), defines)
        y = _resolve_int(element.prop("ypos"), defines)
        if x is None and y is None:
            continue
        asset = _image_path(
            element.prop("idle")
            or element.prop("idle_background")
            or element.prop("background")
            or element.prop("hover")
        )
        if asset:
            probe.assets.append(asset)
        probe.buttons.append(
            QuickButton(
                x=x if x is not None else 0,
                y=y if y is not None else 0,
                asset=asset,
            )
        )
    return probe


# ---------------------------------------------------------------------------
# public probe
# ---------------------------------------------------------------------------


def probe_style(
    scripts: Iterable[ScriptFile],
    archive: GameArchive | None = None,
    *,
    max_samples: int = 10,
) -> StyleProbeResult:
    scripts = list(scripts)
    result = StyleProbeResult()
    evidence = StyleEvidence()

    defines: dict[str, str] = {}
    for script in scripts:
        for name, value in script.defines().items():
            short = name.split(".")[-1]
            defines.setdefault(short, value)
            if name.startswith("gui."):
                defines.setdefault(name[len("gui.") :], value)
    result.notes.append(f"read {len(defines)} GUI definitions")

    for role, keys in _COLOR_KEYS.items():
        for key in keys:
            raw = defines.get(key)
            if raw is None:
                continue
            value = _resolve(raw, defines)
            color = normalize_color(value)
            if color:
                evidence.colors[role] = color
                evidence.sources.append(f"gui.{key} = {value}")
                break

    for role, keys in _FONT_KEYS.items():
        for key in keys:
            raw = defines.get(key)
            if raw is None:
                continue
            font = _resolve_str(raw, defines)
            if font:
                evidence.fonts[role] = font
                evidence.sources.append(f"gui.{key} = {font}")
                break

    for role, key in _SIZE_KEYS.items():
        raw = defines.get(key)
        if raw is None:
            continue
        size = _resolve_int(raw, defines)
        if size and size > 0:
            evidence.sizes[role] = size
            evidence.sources.append(f"gui.{key} = {size}")

    evidence.screen_size = _find_screen_size(scripts, defines)
    if evidence.screen_size:
        result.notes.append(f"screen size {evidence.screen_size[0]}x{evidence.screen_size[1]}")

    backgrounds = {
        "game_menu_background": _resolve_str(defines.get("game_menu_background", ""), defines),
        "main_menu_background": _resolve_str(defines.get("main_menu_background", ""), defines),
    }
    styles = _collect_styles(scripts)
    quick_menu = _find_quick_menu(scripts, defines, evidence.screen_size)
    result.quick_menu = quick_menu

    # -- gather asset candidates --------------------------------------------
    candidates: dict[str, tuple[str, str]] = {}  # path -> (semantic name, origin)

    def add_candidate(path: str, semantic: str, origin: str) -> None:
        path = path.strip().strip("'\"")
        if not path or not archive or not archive.exists(path):
            return
        candidates.setdefault(path, (semantic, origin))

    menu_bg = backgrounds["game_menu_background"]
    if menu_bg:
        add_candidate(menu_bg, "menu_bg", "gui.game_menu_background")

    if quick_menu is not None:
        normal_added = 0
        for index, asset in enumerate(quick_menu.assets):
            lowered = asset.lower()
            if any(word in lowered for word in ("click", "hover", "selected")):
                add_candidate(asset, "quick_icon_hover", "quick_menu")
            else:
                if normal_added < 3:
                    add_candidate(asset, "quick_icon", "quick_menu")
                    normal_added += 1

    priority = ("option_bg", "panel", "dialog_bg", "menu_bg", "quick_icon", "quick_icon_hover")
    for style_name, properties in styles.items():
        for key, raw in properties.items():
            if key not in ("background", "idle_background", "hover_background", "idle", "hover"):
                continue
            path = _image_path(raw)
            if not path:
                continue
            semantic = _classify_asset(path, style_name)
            if semantic == "asset" and not _usable_panel_asset(path):
                continue
            add_candidate(path, semantic, f"style {style_name}")

    # Screens often carry their backgrounds inline (say window, choice frames).
    for script in scripts:
        for info in script.screens().values():
            for element in info.walk():
                for key in ("background", "idle", "idle_background", "hover"):
                    raw = element.prop(key)
                    if not raw:
                        continue
                    path = _image_path(raw)
                    if not path:
                        continue
                    context = f"{info.name} {element.kind}"
                    semantic = _classify_asset(path, context)
                    if semantic == "asset" and not _usable_panel_asset(path):
                        continue
                    add_candidate(path, semantic, f"screen {info.name}")

    ordered = sorted(
        candidates.items(),
        key=lambda item: (
            priority.index(item[1][0]) if item[1][0] in priority else len(priority),
            item[0],
        ),
    )

    samples: list[UiSample] = []
    samples_by_name: dict[str, UiSample] = {}
    for path, (semantic, origin) in ordered[:max_samples]:
        if archive is None:
            break
        try:
            data = archive.read(path)
            size = png_size(data)
            stats = color_stats(data)
        except (ArchiveError, PngError, KeyError) as exc:
            result.warnings.append(f"could not sample {path}: {exc}")
            continue
        if stats.coverage < 0.02:
            result.warnings.append(f"skipped mostly transparent asset {path}")
            continue
        sample = UiSample(
            name=semantic,
            path=path,
            color=stats.dominant,
            average=stats.average,
            alpha=round(stats.coverage, 3),
            width=size[0],
            height=size[1],
        )
        samples.append(sample)
        samples_by_name.setdefault(semantic, sample)
        evidence.sources.append(f"sampled {path}: {stats.dominant}")
        if quick_menu is not None and semantic in ("quick_icon", "quick_icon_hover"):
            for button in quick_menu.buttons:
                if button.asset == path and not button.width:
                    button.width = size[0]
                    button.height = size[1]

    # The quick menu icons are usually the clearest expression of the game's
    # accent colour, so they win over the default GUI template when saturated.
    quick_icon = samples_by_name.get("quick_icon")
    declared_accent = evidence.colors.get("accent", "")
    if quick_icon and declared_accent in ("", "#0099ff", "#ff0000"):
        # The blue accent from Ren'Py's GUI template tells us nothing about
        # this game; its own quick menu icons are a better source.
        accent = normalize_color(quick_icon.color)
        if accent and _luminance(accent) < 0.28:
            accent = _lighten(accent, 0.3)
        if accent:
            evidence.colors["accent"] = accent
            evidence.sources.append(f"accent from {quick_icon.path}: {accent}")

    panel = samples_by_name.get("option_bg") or samples_by_name.get("dialog_bg") or samples_by_name.get("menu_bg")
    if panel is not None:
        panel_color = normalize_color(panel.average) or normalize_color(panel.color)
        if panel_color:
            evidence.colors["panel"] = panel_color
            samples.append(
                UiSample(
                    name="panel",
                    path=panel.path,
                    color=panel_color,
                    average=panel_color,
                    alpha=panel.alpha,
                    width=panel.width,
                    height=panel.height,
                )
            )
            evidence.sources.append(f"panel from {panel.path}: {panel_color}")

    evidence.ui_samples = samples
    evidence.background_image = _resolve_str(defines.get("game_menu_background", ""), defines)
    evidence.warnings = list(result.warnings)
    result.evidence = evidence

    if quick_menu is not None and quick_menu.found and not quick_menu.has_source:
        result.notes.append(
            "quick_menu ships only as .rpyc; the entry button will be drawn as an overlay companion"
        )
    return result
