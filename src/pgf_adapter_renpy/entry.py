"""Decide how the flowchart is opened inside the game and generate the hook.

Ren'Py's quick menu is a screen.  When the game ships its source we can append
a button without touching the original file: the generated file copies the
quick menu body under a new name and defines a wrapper ``quick_menu`` screen at
a late init priority.  When only compiled scripts exist that is impossible
without decompiling screen language, so the fallback draws a companion button
as an overlay next to the original quick menu.

A hotkey screen is always installed as well, so the chart stays reachable even
if the quick menu is hidden or the game changes its layout.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace

from pgf_core.version import __version__
from pgf_style import StyleTokens, contrast_text, darken, lighten

from .assets import UI_DIR
from .screen_emit import GeneratedFile
from .style_probe import QuickMenuProbe

__all__ = [
    "EntryPlan",
    "EntryOptions",
    "build_entry_plan",
    "HOTKEY_NAME",
    "HOTKEY_KEYS",
]

HOTKEY_NAME = "pgf_flowchart"
HOTKEY_KEYS = ("K_F10",)
GAMEPAD_KEYS = ("pad_y", "pad_start")
AUX_MODES = ("title_menu", "game_menu")


@dataclass(frozen=True)
class EntryOptions:
    game_name: str = "Ren'Py game"
    version: str = __version__
    screen_size: tuple[int, int] | None = None
    hotkey: tuple[str, ...] = HOTKEY_KEYS
    prefer_quick_menu_patch: bool = True
    force_mode: str = ""  # "", "quick_menu_patch", "overlay_button", "title_menu", "game_menu", "gamepad"
    button_label: str = "流程图"
    gamepad: bool = False


@dataclass
class EntryPlan:
    mode: str
    file: GeneratedFile
    position: tuple[int, int] = (0, 0)
    size: tuple[int, int] = (0, 0)
    hotkey: tuple[str, ...] = HOTKEY_KEYS
    reason: str = ""
    warnings: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def patched_quick_menu(self) -> bool:
        return self.mode == "quick_menu_patch"

    def summary(self) -> dict[str, object]:
        return {
            "mode": self.mode,
            "position": list(self.position),
            "size": list(self.size),
            "hotkey": list(self.hotkey),
            "reason": self.reason,
            "warnings": len(self.warnings),
        }


def _button_size(quick: QuickMenuProbe | None) -> tuple[int, int]:
    height = 58
    width = 150
    if quick is not None:
        row = quick.row_buttons()
        if row:
            heights = [button.height for button in row if button.height]
            widths = [button.width for button in row if button.width]
            if heights:
                height = max(44, min(78, int(round(median(heights)))))
            if widths:
                width = max(120, min(210, int(round(median(widths) * 1.15))))
    return width, height


def median(values: list[int]) -> float:
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return float(ordered[middle])
    return (ordered[middle - 1] + ordered[middle]) / 2.0


def _button_colors(tokens: StyleTokens) -> tuple[str, str, str]:
    fill = tokens.accent
    hover = lighten(fill, 0.18)
    text = contrast_text(fill, "#ffffff", "#121417")
    # Light accents need a slightly darker hover so the state is visible.
    if text == "#121417":
        hover = darken(fill, 0.12)
    return fill, hover, text


def _font_line(tokens: StyleTokens, indent: str = "        ") -> str:
    if not tokens.font:
        return ""
    return f'{indent}font "{tokens.font}"\n'


def _header(options: EntryOptions, mode: str) -> str:
    return (
        f"# PaperGalFlow v{options.version} -- generated entry hook, do not edit.\n"
        f"# Game: {options.game_name}\n"
        f"# Mode: {mode}\n"
        f"# Hotkey: {', '.join(options.hotkey)} (keymap name {HOTKEY_NAME!r})\n"
        f"# Uninstall: delete every pgf_*.rpy file from the game directory.\n"
    )


def _hotkey_python(options: EntryOptions) -> str:
    keys = ", ".join(repr(key) for key in options.hotkey)
    return (
        "init -30 python:\n"
        f"    config.keymap[{HOTKEY_NAME!r}] = [{keys}]\n"
        "    if \"pgf_hotkey\" not in config.overlay_screens:\n"
        "        config.overlay_screens.append(\"pgf_hotkey\")\n"
    )


def _hotkey_screen() -> str:
    return (
        "screen pgf_hotkey():\n"
        "    zorder 5\n"
        f"    key {HOTKEY_NAME!r} action ShowMenu(\"pgf_flowchart\")\n"
    )


def _overlay_screen(
    tokens: StyleTokens,
    position: tuple[int, int],
    size: tuple[int, int],
    options: EntryOptions,
) -> str:
    fill, hover, text_color = _button_colors(tokens)
    x, y = position
    width, height = size
    font = f'            font "{tokens.font}"\n' if tokens.font else ""
    return (
        "init python:\n"
        "    if \"pgf_quick_button\" not in config.overlay_screens:\n"
        "        config.overlay_screens.append(\"pgf_quick_button\")\n"
        "\n"
        "screen pgf_quick_button():\n"
        "    zorder 150\n"
        "    button:\n"
        f"        xpos {x}\n"
        f"        ypos {y}\n"
        f"        xysize ({width}, {height})\n"
        f'        background Frame("{UI_DIR}/accent_button.png", 20, 20)\n'
        f'        hover_background Frame("{UI_DIR}/accent_button_hover.png", 20, 20)\n'
        "        action ShowMenu(\"pgf_flowchart\")\n"
        f"        text \"{options.button_label}\":\n"
        f"{font}"
        f"            size {max(16, min(26, tokens.node_text_size - 2))}\n"
        f"            color \"{text_color}\"\n"
        "            xalign 0.5\n"
        "            yalign 0.5\n"
    )


def build_entry_plan(
    tokens: StyleTokens,
    quick: QuickMenuProbe | None,
    options: EntryOptions | None = None,
) -> EntryPlan:
    options = options or EntryOptions()
    if options.force_mode == "gamepad":
        options = replace(options, force_mode="overlay_button", gamepad=True)
    if options.gamepad and not any(key in options.hotkey for key in GAMEPAD_KEYS):
        options = replace(options, hotkey=tuple(options.hotkey) + GAMEPAD_KEYS)
    screen_size = options.screen_size or (quick.screen_size if quick else None) or (1920, 1080)
    size = _button_size(quick)
    if quick is not None:
        position = quick.placement(size[0], size[1], gap=14)
    else:
        position = (max(20, screen_size[0] - size[0] - 48), max(20, screen_size[1] - size[1] - 120))
    warnings: list[str] = []
    notes: list[str] = []

    if options.force_mode in AUX_MODES:
        return _build_aux_entry(tokens, options.force_mode, screen_size, options, warnings, notes)

    can_patch = bool(
        options.prefer_quick_menu_patch
        and quick is not None
        and quick.found
        and quick.source.strip()
    )
    if options.force_mode == "overlay_button":
        can_patch = False
    elif options.force_mode == "quick_menu_patch" and not can_patch:
        warnings.append("quick_menu_patch was requested but no usable screen source could be reconstructed")

    if can_patch:
        if quick is not None and quick.decompiled:  # type: ignore[union-attr]
            reason = (
                "quick_menu was reconstructed from compiled SL2; appending a button "
                "without modifying the original archive"
            )
            notes.append("quick_menu source was decompiled from .rpyc; review the generated wrapper if the game uses custom ATL")
        else:
            reason = "quick_menu source is available; appending a button without touching the original"
        plan = _build_patch(
            tokens,
            quick,  # type: ignore[arg-type]
            position,
            size,
            options,
            warnings,
            notes,
            reason,
        )
    else:
        if quick is None:
            reason = "no quick menu screen was found; using the overlay companion button"
        elif not quick.has_source:
            reason = "quick_menu ships only as compiled code; using the overlay companion button"
        elif options.force_mode == "overlay_button":
            reason = "overlay mode was forced"
        else:
            reason = "quick menu layout is not usable for a patch; using the overlay companion button"
        plan = _build_overlay(tokens, position, size, options, warnings, notes, reason)
    return plan


def _build_aux_entry(
    tokens: StyleTokens,
    mode: str,
    screen_size: tuple[int, int],
    options: EntryOptions,
    warnings: list[str],
    notes: list[str],
) -> EntryPlan:
    """A standalone overlay button for the title screen or the game menu."""

    width, height = 150, 58
    x = 40
    y = max(24, screen_size[1] - height - 96)
    screen_name = "pgf_title_button" if mode == "title_menu" else "pgf_game_menu_button"
    if mode == "title_menu":
        condition = "if main_menu:"
        reason = "title menu entry: a companion button is shown on the title screen"
        notes.append("the title button opens the read-only chart with Show(...); history is usually empty before loading a save")
    else:
        condition = 'if not main_menu and renpy.get_screen("game_menu") is not None:'
        reason = "game menu entry: a companion button is shown while the game menu is open"
        notes.append("the game menu button overlays the menu and closes back to it")
    fill, hover, text_color = _button_colors(tokens)
    font = f'                font "{tokens.font}"\n' if tokens.font else ""
    content = "\n".join(
        [
            _header(options, mode),
            "",
            _hotkey_python(options),
            "",
            _hotkey_screen(),
            "",
            "init python:",
            f"    if {screen_name!r} not in config.always_shown_screens:",
            f"        config.always_shown_screens.append({screen_name!r})",
            "",
            f"screen {screen_name}():",
            "    zorder 150",
            f"    {condition}",
            "        button:",
            f"            xpos {x}",
            f"            ypos {y}",
            f"            xysize ({width}, {height})",
            f'            background Frame("{UI_DIR}/accent_button.png", 20, 20)',
            f'            hover_background Frame("{UI_DIR}/accent_button_hover.png", 20, 20)',
            '            action Show("pgf_flowchart", pgf_from_menu=True)',
            f'            text "{options.button_label}":',
            font,
            f"                size {max(16, min(26, tokens.node_text_size - 2))}",
            f'                color "{text_color}"',
            "                xalign 0.5",
            "                yalign 0.5",
        ]
    ) + "\n"
    return EntryPlan(
        mode=mode,
        file=GeneratedFile("pgf_menu_hook.rpy", content, "entry"),
        position=(x, y),
        size=(width, height),
        hotkey=tuple(options.hotkey),
        reason=reason,
        warnings=warnings,
        notes=notes,
    )


def _build_overlay(
    tokens: StyleTokens,
    position: tuple[int, int],
    size: tuple[int, int],
    options: EntryOptions,
    warnings: list[str],
    notes: list[str],
    reason: str,
) -> EntryPlan:
    content = "\n".join(
        [
            _header(options, "overlay_button"),
            "",
            _hotkey_python(options),
            "",
            _hotkey_screen(),
            "\n" + _overlay_screen(tokens, position, size, options),
        ]
    )
    notes.append("the overlay button is shown next to the original quick menu when the overlay is visible")
    return EntryPlan(
        mode="overlay_button",
        file=GeneratedFile("pgf_menu_hook.rpy", content, "entry"),
        position=position,
        size=size,
        hotkey=tuple(options.hotkey),
        reason=reason,
        warnings=warnings,
        notes=notes,
    )


def _screen_property_lines(properties: dict[str, str]) -> list[str]:
    lines: list[str] = []
    for key in sorted(properties):
        if not key.isidentifier():
            continue
        value = str(properties[key]).strip()
        if value:
            lines.append(f"    {key} {value}")
    return lines


def _build_patch(
    tokens: StyleTokens,
    quick: QuickMenuProbe,
    position: tuple[int, int],
    size: tuple[int, int],
    options: EntryOptions,
    warnings: list[str],
    notes: list[str],
    reason: str,
) -> EntryPlan:
    parameters = quick.parameters if quick.parameters else "()"
    body = "\n".join(
        ("    " + line) if line.strip() else "" for line in quick.source.splitlines()
    )
    property_lines = _screen_property_lines(quick.properties)
    fill, hover, text_color = _button_colors(tokens)
    x, y = position
    width, height = size
    font = f'            font "{tokens.font}"\n' if tokens.font else ""
    content = "\n".join(
        [
            _header(options, "quick_menu_patch"),
            "",
            _hotkey_python(options),
            "",
            _hotkey_screen(),
            "",
            "init offset = 999",
            "",
            f"screen pgf_quick_menu_base{parameters}:",
            *property_lines,
            body,
            "",
            f"screen quick_menu{parameters}:",
            *property_lines,
            "    use pgf_quick_menu_base",
            "",
            "    button:",
            f"        xpos {x}",
            f"        ypos {y}",
            f"        xysize ({width}, {height})",
            f'        background Frame("{UI_DIR}/accent_button.png", 20, 20)',
            f'        hover_background Frame("{UI_DIR}/accent_button_hover.png", 20, 20)',
            '        action ShowMenu("pgf_flowchart")',
            '        text "流程图":',
            font,
            f"            size {max(16, min(26, tokens.node_text_size - 2))}",
            f'            color "{text_color}"',
            "            xalign 0.5",
            "            yalign 0.5",
        ]
    ) + "\n"
    notes.append(
        "the original quick_menu screen is copied "
        + ("from decompiled SL2 " if quick.decompiled else "verbatim ")
        + "and redefined at init priority 499"
    )
    warnings.extend(quick.decompile_warnings)
    if "variant" in quick.source or "variant" in quick.properties:
        warnings.append("quick_menu source mentions screen variants; the copied screen may not cover all variants")
    return EntryPlan(
        mode="quick_menu_patch",
        file=GeneratedFile("pgf_menu_hook.rpy", content, "entry"),
        position=position,
        size=size,
        hotkey=tuple(options.hotkey),
        reason=reason,
        warnings=warnings,
        notes=notes,
    )
