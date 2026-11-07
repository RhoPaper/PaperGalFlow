"""Generate the standalone Ren'Py ``screen pgf_flowchart`` file.

The generator is a pure function of the story graph, the layout, the style
tokens and a few options.  It embeds only data and a screen:

* the precomputed graph data (nodes, edges, labels, predecessors),
* node states read from Ren'Py's own ``seen_label`` database,
* a full screen with markup, legend, zoom and a scrollable viewport.

It never writes game state, never hooks a label callback and never synthesizes
menus.  The only call into the game's flow is ``jump_out_of_context`` to an
existing scene label; clicking a choice/condition node does nothing because
those have no scene label of their own.
"""

from __future__ import annotations

import pprint
from dataclasses import dataclass

from pgf_core.layout import Layout, Point
from pgf_core.model import EdgeKind, FlowGraph, NodeKind
from pgf_core.version import __version__
from pgf_style import StyleTokens, build_theme

from .assets import ui_manifest

__all__ = ["GeneratedFile", "FlowchartEmitOptions", "emit_flowchart_screen"]

DEFAULT_SCREEN_SIZE = (1920, 1080)


@dataclass(frozen=True)
class GeneratedFile:
    name: str
    content: str = ""
    role: str = "screen"
    data: bytes | None = None

    @property
    def is_binary(self) -> bool:
        return self.data is not None

    @property
    def payload(self) -> bytes:
        return self.data if self.data is not None else self.content.encode("utf-8")

    @property
    def byte_size(self) -> int:
        return len(self.payload)


@dataclass
class FlowchartEmitOptions:
    game_name: str = "Ren'Py game"
    entry_label: str = ""
    screen_size: tuple[int, int] | None = None
    show_subtitles: bool = False
    max_title_chars: int = 36
    max_edge_label_chars: int = 26
    show_condition_labels: bool = False
    version: str = __version__
    header_comment: bool = True


# ---------------------------------------------------------------------------
# data extraction
# ---------------------------------------------------------------------------


def _clean(text: str, limit: int) -> str:
    from pgf_adapter_renpy.analyze import clean_text

    return clean_text(text, limit)


def _node_rows(
    graph: FlowGraph,
    layout: Layout,
    options: FlowchartEmitOptions,
) -> list[tuple[str, str, str, str, str, str, str, str, int, int, int, int]]:
    rows = []
    for node in graph.nodes.values():
        rect = layout.positions.get(node.id)
        if rect is None:
            continue
        title = _clean(node.title, options.max_title_chars) or "未命名"
        subtitle = _clean(node.subtitle, options.max_title_chars) if options.show_subtitles else ""
        rows.append(
            (
                node.id,
                node.kind.value,
                title,
                subtitle,
                str(node.meta.get("history_text", "")),
                str(node.meta.get("history_text2", "")),
                str(node.meta.get("history_fallback", "")),
                str(node.meta.get("label", "")),
                rect.x,
                rect.y,
                rect.w,
                rect.h,
            )
        )
    return rows


def _edge_data(
    layout: Layout,
    rows: list[tuple[str, str, str, str, str, str, str, str, int, int, int, int]],
    options: FlowchartEmitOptions,
) -> tuple[dict[str, list[tuple[int, int, int, int]]], list[tuple[str, int, int]], list[str]]:
    node_rects = [
        (row[8], row[9], row[8] + row[10], row[9] + row[11]) for row in rows
    ]
    rect_by_id = {
        row[0]: (row[8], row[9], row[8] + row[10], row[9] + row[11]) for row in rows
    }
    segments: dict[str, list[tuple[int, int, int, int]]] = {}
    labels: list[tuple[str, int, int]] = []
    order: list[str] = []
    thickness = 4

    def inside_node(point: Point, padding: int = 2) -> bool:
        return any(
            left - padding <= point.x <= right + padding
            and top - padding <= point.y <= bottom + padding
            for left, top, right, bottom in node_rects
        )

    for edge in layout.edges:
        kind = edge.kind.value
        if kind not in segments:
            segments[kind] = []
            order.append(kind)
        points = edge.points
        for first, second in zip(points, points[1:]):
            if first.x == second.x:
                top = min(first.y, second.y)
                height = abs(first.y - second.y)
                if height <= 0:
                    continue
                segments[kind].append((first.x - thickness // 2, top, thickness, height))
            else:
                left = min(first.x, second.x)
                width = abs(first.x - second.x)
                if width <= 0:
                    continue
                segments[kind].append((left, first.y - thickness // 2, width, thickness))
        label = _clean(edge.label, options.max_edge_label_chars)
        if edge.kind is EdgeKind.CONDITION and not options.show_condition_labels:
            label = ""
        if label:
            target = rect_by_id.get(edge.target)
            if target is not None and edge.kind in (EdgeKind.CHOICE, EdgeKind.CONDITION):
                label_x = (target[0] + target[2]) // 2
                label_y = target[1] - 20
            else:
                label_x, label_y = edge.label_at.x, edge.label_at.y
            if not inside_node(Point(label_x, label_y)):
                labels.append((label, label_x, label_y))

    preferred = ("flow", "choice", "condition", "call")
    order = sorted(order, key=lambda name: preferred.index(name) if name in preferred else 99)
    return segments, labels, order


def _predecessors(graph: FlowGraph) -> dict[str, tuple[str, ...]]:
    result: dict[str, set[str]] = {}
    for edge in graph.edges:
        if edge.kind is EdgeKind.CALL:
            continue
        result.setdefault(edge.target, set()).add(edge.source)
    return {target: tuple(sorted(sources)) for target, sources in result.items()}


def _legend(ui: dict[str, object]) -> list[tuple[str, str]]:
    return [
        (str(ui["legend_read"]), "已读"),
        (str(ui["legend_unread"]), "未读"),
        (str(ui["legend_locked"]), "锁定"),
        (str(ui["legend_ending"]), "结局"),
    ]


def _default_zoom(layout: Layout, screen_size: tuple[int, int]) -> float:
    if layout.width <= 0:
        return 1.0
    available = max(320, screen_size[0] - 48)
    zoom = available / float(layout.width)
    return round(max(0.45, min(1.0, zoom)), 3)


def _python_literal(value: object, indent: int = 0) -> str:
    return pprint.pformat(value, width=104, sort_dicts=False)


def _init_python_block(source: str, priority: int) -> str:
    lines = source.splitlines()
    body = "\n".join(("    " + line) if line.strip() else "" for line in lines)
    return f"init {priority} python:\n{body}\n"


# ---------------------------------------------------------------------------
# screen emission
# ---------------------------------------------------------------------------


def emit_flowchart_screen(
    graph: FlowGraph,
    layout: Layout,
    tokens: StyleTokens,
    options: FlowchartEmitOptions | None = None,
) -> GeneratedFile:
    options = options or FlowchartEmitOptions()
    screen_size = options.screen_size or DEFAULT_SCREEN_SIZE
    rows = _node_rows(graph, layout, options)
    segments, labels, edge_order = _edge_data(layout, rows, options)
    predecessors = _predecessors(graph)
    zoom = _default_zoom(layout, screen_size)
    theme = build_theme(tokens)
    ui = ui_manifest(tokens)

    meta = {
        "tool": "PaperGalFlow",
        "version": options.version,
        "game": options.game_name,
        "entry_label": options.entry_label,
        "entry_node": graph.entry,
        "nodes": len(graph.nodes),
        "edges": len(graph.edges),
        "endings": len(graph.endings()),
        "screen_size": list(screen_size),
        "style_source": tokens.source,
        "style_name": tokens.name,
        "state_source": "renpy.seen_label",
    }

    data_source = "\n".join(
        [
            f"PGF_META = {_python_literal(meta)}",
            f"PGF_CANVAS = {_python_literal((layout.width, layout.height))}",
            f"PGF_SCREEN = {_python_literal(screen_size)}",
            f"PGF_DEFAULT_ZOOM = {zoom!r}",
            f"PGF_ENTRY = {graph.entry!r}",
            f"PGF_NODES = {_python_literal(rows)}",
            f"PGF_PREDECESSORS = {_python_literal(predecessors)}",
            f"PGF_EDGE_SEGMENTS = {_python_literal(segments)}",
            f"PGF_EDGE_LABELS = {_python_literal(labels)}",
            f"PGF_EDGE_ORDER = {_python_literal(edge_order)}",
            f"PGF_LEGEND = {_python_literal(_legend(ui))}",
            f"PGF_UI = {_python_literal(ui)}",
            f"PGF_STYLE = {_python_literal(theme.constants['PGF_STYLE'])}",
        ]
    )

    helpers = _helper_source()
    screen = _screen_source()

    parts: list[str] = []
    if options.header_comment:
        parts.append(_header(graph, options, tokens, screen_size))
    parts.append(_init_python_block(data_source, -35))
    parts.append(_init_python_block(helpers, -30))
    parts.append(theme.style_blocks + "\n")
    parts.append(screen)
    content = "\n".join(part.rstrip("\n") for part in parts) + "\n"
    return GeneratedFile("pgf_flowchart_screen.rpy", content, "screen")


def _header(
    graph: FlowGraph,
    options: FlowchartEmitOptions,
    tokens: StyleTokens,
    screen_size: tuple[int, int],
) -> str:
    return (
        f"# PaperGalFlow v{options.version} -- generated file, do not edit.\n"
        f"# Game: {options.game_name}\n"
        f"# Entry label: {options.entry_label or graph.entry}\n"
        f"# Chart: {len(graph.nodes)} nodes, {len(graph.edges)} edges, "
        f"{len(graph.endings())} endings\n"
        f"# Style: {tokens.name} ({tokens.source}), screen {screen_size[0]}x{screen_size[1]}\n"
        f"# Assets: pgf_ui/*.png (generated nine-patch frames)\n"
        f"# Uninstall: delete every pgf_*.rpy file and the pgf_ui directory.\n"
    )


def _helper_source() -> str:
    return r'''def pgf_text_key(text):
    """Normalize script/history text for matching (drop Ren'Py text tags)."""
    text = str(text or "")
    out = []
    depth = 0
    for ch in text:
        if ch == "{":
            depth += 1
        elif ch == "}":
            if depth:
                depth -= 1
        elif not depth:
            out.append(ch)
    key = " ".join("".join(out).split())
    return key.strip(" \t\r\n「」『』\"'“”‘’（）()【】[]")


def pgf_find_history(entries, texts):
    keys = [pgf_text_key(text) for text in texts if text]
    if not keys:
        return None
    size = len(keys)
    for index in range(len(entries) - size, -1, -1):
        if all(entries[index + offset][0] == keys[offset] for offset in range(size)):
            return entries[index][1]
    return None


def pgf_history_ids():
    """Map nodes to the game's own rollback checkpoints.

    Only values already present in ``_history_list`` are used, exactly like the
    jump-back buttons on the game's HISTORY screen.  Nothing is synthesized and
    no game state is written; nodes without a checkpoint stay non-clickable.
    """
    entries = []
    for entry in getattr(renpy.store, "_history_list", ()) or ():
        identifier = getattr(entry, "rollback_identifier", None)
        if not identifier:
            continue
        try:
            if renpy.get_identifier_checkpoints(identifier) is None:
                continue
        except Exception:
            continue
        key = pgf_text_key(getattr(entry, "what", ""))
        if key:
            entries.append((key, identifier))

    result = {}
    for node in PGF_NODES:
        # When a second line exists, require the full sequence.  Falling back to
        # the first line would map every scene that shares an opening line to
        # the same checkpoint.
        if node[5]:
            identifier = pgf_find_history(entries, (node[4], node[5]))
        else:
            identifier = pgf_find_history(entries, (node[4],))
        if identifier is None and node[6]:
            identifier = pgf_find_history(entries, (node[6],))
        if identifier is not None:
            result[node[0]] = identifier
    return result


def pgf_read_states():
    """Derive node states from the game's own seen-label database.

    Nothing is written: Ren'Py itself records which labels have been seen, and
    this only reads that database through ``renpy.seen_label``.
    """
    seen = {}
    for _pgf_node in PGF_NODES:
        _pgf_key = _pgf_node[7]
        seen[_pgf_node[0]] = bool(_pgf_key) and renpy.seen_label(_pgf_key)
    result = {}
    for _pgf_node in PGF_NODES:
        _pgf_id = _pgf_node[0]
        if _pgf_node[1] == "ending":
            result[_pgf_id] = "ending_read" if seen[_pgf_id] else "ending_locked"
        elif seen[_pgf_id]:
            result[_pgf_id] = "read"
        elif _pgf_id == PGF_ENTRY or any(
            seen[_pgf_prev] for _pgf_prev in PGF_PREDECESSORS.get(_pgf_id, ())
        ):
            result[_pgf_id] = "unread"
        else:
            result[_pgf_id] = "locked"
    return result


def pgf_progress_text(states):
    scenes = [node for node in PGF_NODES if node[1] != "ending"]
    endings = [node for node in PGF_NODES if node[1] == "ending"]
    read = len([node for node in scenes if states.get(node[0]) == "read"])
    reached = len([node for node in endings if states.get(node[0]) == "ending_read"])
    return "已读 %d / %d    结局 %d / %d" % (read, len(scenes), reached, len(endings))


def pgf_node_title(state, title):
    if state in ("locked", "ending_locked"):
        return "？？？"
    return title or "未命名"


def pgf_node_kind_label(kind, state, identifier):
    if kind == "choice":
        base = "选择"
    elif kind == "condition":
        base = "分歧"
    elif kind == "ending":
        base = "结局"
    elif kind == "entry":
        base = "起点"
    else:
        base = ""
    if state in ("locked", "ending_locked"):
        return base
    if not identifier:
        return (base + " · 无历史") if base else "无历史"
    return base


def pgf_node_sensitive(state, identifier):
    return bool(identifier) and state not in ("locked", "ending_locked")


def pgf_palette_key(state, kind):
    if state in ("ending_locked", "ending_read"):
        return "ending"
    if state == "locked":
        return "locked"
    if state == "read":
        return "read"
    if kind == "choice":
        return "choice"
    if kind == "condition":
        return "condition"
    return "unread"


def pgf_scroll(adjustment, delta):
    try:
        adjustment.change(adjustment.value + delta)
    except Exception:
        pass
'''


def _screen_source() -> str:
    return '''\
screen pgf_flowchart():
    modal True
    zorder 200

    default pgf_zoom = PGF_DEFAULT_ZOOM
    default pgf_states = pgf_read_states()
    default pgf_history = pgf_history_ids()
    default pgf_progress = pgf_progress_text(pgf_states)
    default pgf_hover = ""
    default pgf_xadj = ui.adjustment()
    default pgf_yadj = ui.adjustment()

    $ _pgf_screen_w = config.screen_width
    $ _pgf_screen_h = config.screen_height
    $ _pgf_title_h = 86
    $ _pgf_footer_h = 66
    $ _pgf_view_h = _pgf_screen_h - _pgf_title_h - _pgf_footer_h
    $ _pgf_scaled_w = int(PGF_CANVAS[0] * pgf_zoom)
    $ _pgf_scaled_h = int(PGF_CANVAS[1] * pgf_zoom)
    $ _pgf_button_y = 23
    $ _pgf_footer_y = _pgf_screen_h - _pgf_footer_h

    add Solid(PGF_STYLE["colors"]["background"])

    if PGF_STYLE["background_image"] and renpy.loadable(PGF_STYLE["background_image"]):
        add Transform(PGF_STYLE["background_image"], alpha=0.16)

    add Solid(PGF_STYLE["colors"]["overlay"])

    add Frame(PGF_UI["panel_top"], 20, 20):
        xpos 0
        ypos 0
        xysize (_pgf_screen_w, _pgf_title_h)

    text "剧情流程图":
        style "pgf_title_text"
        xpos 42
        ypos 18

    text pgf_progress:
        style "pgf_legend_text"
        xpos 330
        ypos 30

    button:
        xpos (_pgf_screen_w - 316)
        ypos _pgf_button_y
        xysize (46, 40)
        background Frame(PGF_UI["button"], 10, 10)
        hover_background Frame(PGF_UI["button_hover"], 10, 10)
        action SetScreenVariable("pgf_zoom", max(0.35, pgf_zoom - 0.1))
        text "－":
            style "pgf_chrome_text"
            xalign 0.5
            yalign 0.5

    button:
        xpos (_pgf_screen_w - 260)
        ypos _pgf_button_y
        xysize (46, 40)
        background Frame(PGF_UI["button"], 10, 10)
        hover_background Frame(PGF_UI["button_hover"], 10, 10)
        action SetScreenVariable("pgf_zoom", min(2.0, pgf_zoom + 0.1))
        text "＋":
            style "pgf_chrome_text"
            xalign 0.5
            yalign 0.5

    button:
        xpos (_pgf_screen_w - 204)
        ypos _pgf_button_y
        xysize (78, 40)
        background Frame(PGF_UI["button"], 10, 10)
        hover_background Frame(PGF_UI["button_hover"], 10, 10)
        action SetScreenVariable("pgf_zoom", PGF_DEFAULT_ZOOM)
        text "适应":
            style "pgf_chrome_text"
            xalign 0.5
            yalign 0.5

    button:
        id "pgf_close"
        xpos (_pgf_screen_w - 116)
        ypos _pgf_button_y
        xysize (86, 40)
        background Frame(PGF_UI["button"], 10, 10)
        hover_background Frame(PGF_UI["button_hover"], 10, 10)
        action Return()
        text "关闭":
            style "pgf_chrome_text"
            xalign 0.5
            yalign 0.5

    viewport:
        xpos 0
        ypos _pgf_title_h
        xysize (_pgf_screen_w, _pgf_view_h)
        mousewheel True
        draggable True
        xadjustment pgf_xadj
        yadjustment pgf_yadj

        fixed:
            xysize (max(_pgf_screen_w, _pgf_scaled_w), max(_pgf_view_h, _pgf_scaled_h))

            fixed:
                at Transform(zoom=pgf_zoom)
                xpos max(0, (_pgf_screen_w - _pgf_scaled_w) // 2)
                ypos 0
                xysize PGF_CANVAS

                for _pgf_kind in PGF_EDGE_ORDER:
                    for _pgf_seg in PGF_EDGE_SEGMENTS[_pgf_kind]:
                        add Solid(PGF_STYLE["edges"][_pgf_kind]):
                            xpos _pgf_seg[0]
                            ypos _pgf_seg[1]
                            xysize (_pgf_seg[2], _pgf_seg[3])

                for _pgf_label in PGF_EDGE_LABELS:
                    frame:
                        xpos _pgf_label[1]
                        ypos _pgf_label[2]
                        xanchor 0.5
                        yanchor 0.5
                        background Frame(PGF_UI["label"], 12, 12)
                        padding (10, 3)
                        text _pgf_label[0]:
                            style "pgf_edge_text"

                for _pgf_node in PGF_NODES:
                    $ _pgf_state = pgf_states.get(_pgf_node[0], "locked")
                    $ _pgf_ident = pgf_history.get(_pgf_node[0])
                    $ _pgf_pal = PGF_STYLE["palettes"][pgf_palette_key(_pgf_state, _pgf_node[1])]

                    add Frame(PGF_UI["shadow"], PGF_UI["frame"], PGF_UI["frame"]):
                        xpos (_pgf_node[8] - 4)
                        ypos (_pgf_node[9] + 3)
                        xysize (_pgf_node[10] + 8, _pgf_node[11] + 8)

                    button:
                        xpos _pgf_node[8]
                        ypos _pgf_node[9]
                        xysize (_pgf_node[10], _pgf_node[11])
                        background Frame(PGF_UI["node_" + pgf_palette_key(_pgf_state, _pgf_node[1])], PGF_UI["frame"], PGF_UI["frame"])
                        hover_background Frame(PGF_UI["node_" + pgf_palette_key(_pgf_state, _pgf_node[1]) + "_hover"], PGF_UI["frame"], PGF_UI["frame"])
                        insensitive_background Frame(PGF_UI["node_" + pgf_palette_key(_pgf_state, _pgf_node[1])], PGF_UI["frame"], PGF_UI["frame"])
                        sensitive pgf_node_sensitive(_pgf_state, _pgf_ident)
                        action Confirm("确定要跳转到该处吗？", yes=RollbackToIdentifier(_pgf_ident or ""), no=None, confirm_selected=False)
                        hovered SetScreenVariable("pgf_hover", pgf_node_title(_pgf_state, _pgf_node[2]))
                        unhovered SetScreenVariable("pgf_hover", "")

                        fixed:
                            xysize (_pgf_node[10], _pgf_node[11])

                            text pgf_node_title(_pgf_state, _pgf_node[2]):
                                style "pgf_node_text"
                                color _pgf_pal["text"]
                                xpos 23
                                ypos 10
                                xsize (_pgf_node[10] - 37)
                                line_spacing 2

                            text pgf_node_kind_label(_pgf_node[1], _pgf_state, _pgf_ident):
                                style "pgf_small_text"
                                color _pgf_pal["strip"]
                                xpos 23
                                ypos (_pgf_node[11] - 26)

    add PGF_UI["bar_shadow"]:
        xpos 0
        ypos _pgf_title_h
        xysize (_pgf_screen_w, 28)

    add Frame(PGF_UI["panel_bottom"], 20, 20):
        xpos 0
        ypos _pgf_footer_y
        xysize (_pgf_screen_w, _pgf_footer_h)

    hbox:
        xpos 32
        ypos (_pgf_footer_y + 13)
        spacing 26

        for _pgf_legend_item in PGF_LEGEND:
            hbox:
                spacing 8
                add _pgf_legend_item[0]:
                    xysize (18, 18)
                    yalign 0.5
                text _pgf_legend_item[1]:
                    style "pgf_legend_text"
                    yalign 0.5

    text ("拖拽 / 滚轮浏览 · 仅可回滚到历史记录中的节点" if not pgf_hover else pgf_hover):
        style "pgf_small_text"
        xpos (_pgf_screen_w // 2)
        xanchor 0.5
        ypos (_pgf_footer_y + 22)

    button:
        xpos (_pgf_screen_w - 182)
        ypos (_pgf_footer_y + 14)
        xysize (38, 38)
        background Frame(PGF_UI["button"], 10, 10)
        hover_background Frame(PGF_UI["button_hover"], 10, 10)
        action Function(pgf_scroll, pgf_yadj, -280)
        text "↑":
            style "pgf_chrome_text"
            xalign 0.5
            yalign 0.5

    button:
        xpos (_pgf_screen_w - 138)
        ypos (_pgf_footer_y + 14)
        xysize (38, 38)
        background Frame(PGF_UI["button"], 10, 10)
        hover_background Frame(PGF_UI["button_hover"], 10, 10)
        action Function(pgf_scroll, pgf_yadj, 280)
        text "↓":
            style "pgf_chrome_text"
            xalign 0.5
            yalign 0.5

    button:
        xpos (_pgf_screen_w - 94)
        ypos (_pgf_footer_y + 14)
        xysize (38, 38)
        background Frame(PGF_UI["button"], 10, 10)
        hover_background Frame(PGF_UI["button_hover"], 10, 10)
        action Function(pgf_scroll, pgf_xadj, -360)
        text "←":
            style "pgf_chrome_text"
            xalign 0.5
            yalign 0.5

    button:
        xpos (_pgf_screen_w - 50)
        ypos (_pgf_footer_y + 14)
        xysize (38, 38)
        background Frame(PGF_UI["button"], 10, 10)
        hover_background Frame(PGF_UI["button_hover"], 10, 10)
        action Function(pgf_scroll, pgf_xadj, 360)
        text "→":
            style "pgf_chrome_text"
            xalign 0.5
            yalign 0.5

    key "game_menu" action Return()
'''
