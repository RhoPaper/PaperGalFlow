"""Generate the standalone Ren'Py ``screen pgf_flowchart`` file.

The generator is a pure function of the story graph, the layout, the style
tokens and a few options.  It embeds:

* the runtime state kernel (so visited state is read and written from inside
  the generated screen code, without any external process),
* the precomputed graph data (nodes, edges, labels, label map),
* a full screen with markup, legend, zoom and a scrollable viewport.

Nothing is computed from the game's scripts at runtime.
"""

from __future__ import annotations

import pprint
from dataclasses import dataclass

from pgf_core.layout import Layout, Point
from pgf_core.model import EdgeKind, FlowGraph, NodeKind
from pgf_core.state import runtime_kernel_source
from pgf_core.version import __version__
from pgf_style import StyleTokens, build_theme

__all__ = ["GeneratedFile", "FlowchartEmitOptions", "emit_flowchart_screen"]

DEFAULT_SCREEN_SIZE = (1920, 1080)


@dataclass(frozen=True)
class GeneratedFile:
    name: str
    content: str
    role: str = "screen"

    @property
    def byte_size(self) -> int:
        return len(self.content.encode("utf-8"))


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
) -> list[tuple[str, str, str, str, str, int, int, int, int]]:
    rows = []
    for node in graph.nodes.values():
        rect = layout.positions.get(node.id)
        if rect is None:
            continue
        title = _clean(node.title, options.max_title_chars) or "未命名"
        subtitle = _clean(node.subtitle, options.max_title_chars) if options.show_subtitles else ""
        label = str(node.meta.get("label", ""))
        rows.append(
            (
                node.id,
                node.kind.value,
                title,
                subtitle,
                label,
                rect.x,
                rect.y,
                rect.w,
                rect.h,
            )
        )
    return rows


def _edge_data(
    layout: Layout,
    rows: list[tuple[str, str, str, str, str, int, int, int, int]],
    options: FlowchartEmitOptions,
) -> tuple[dict[str, list[tuple[int, int, int, int]]], list[tuple[str, int, int]], list[str]]:
    node_rects = [
        (row[5], row[6], row[5] + row[7], row[6] + row[8]) for row in rows
    ]
    rect_by_id = {
        row[0]: (row[5], row[6], row[5] + row[7], row[6] + row[8]) for row in rows
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


def _label_map(graph: FlowGraph) -> dict[str, list[str]]:
    result: dict[str, list[str]] = {}
    for node in graph.nodes.values():
        label = str(node.meta.get("label", ""))
        if label:
            result.setdefault(label, []).append(node.id)
    return result


def _legend(tokens: StyleTokens) -> list[tuple[str, str]]:
    return [
        (tokens.palette("read").strip, "已读"),
        (tokens.palette("unread").strip, "未读"),
        (tokens.palette("locked").strip, "锁定"),
        (tokens.palette("ending").strip, "结局"),
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
    label_map = _label_map(graph)
    endings = [node.id for node in graph.nodes.values() if node.kind is NodeKind.ENDING]
    kernel_edges = [(edge.source, edge.target, edge.kind.value) for edge in graph.edges]
    zoom = _default_zoom(layout, screen_size)
    theme = build_theme(tokens)

    meta = {
        "tool": "PaperGalFlow",
        "version": options.version,
        "game": options.game_name,
        "entry_label": options.entry_label,
        "entry_node": graph.entry,
        "nodes": len(graph.nodes),
        "edges": len(graph.edges),
        "endings": len(endings),
        "screen_size": list(screen_size),
        "style_source": tokens.source,
        "style_name": tokens.name,
        "persistent_key": "pgf_progress",
    }

    data_source = "\n".join(
        [
            f"PGF_META = {_python_literal(meta)}",
            f"PGF_CANVAS = {_python_literal((layout.width, layout.height))}",
            f"PGF_SCREEN = {_python_literal(screen_size)}",
            f"PGF_DEFAULT_ZOOM = {zoom!r}",
            f"PGF_SCROLLBARS = {_python_literal('both')}",
            f"PGF_ENTRY = {graph.entry!r}",
            f"PGF_NODES = {_python_literal(rows)}",
            f"PGF_EDGE_SEGMENTS = {_python_literal(segments)}",
            f"PGF_EDGE_LABELS = {_python_literal(labels)}",
            f"PGF_EDGE_ORDER = {_python_literal(edge_order)}",
            f"PGF_LABEL_MAP = {_python_literal(label_map)}",
            f"PGF_ENDINGS = {_python_literal(endings)}",
            f"PGF_KERNEL_EDGES = {_python_literal(kernel_edges)}",
            f"PGF_LEGEND = {_python_literal(_legend(tokens))}",
            f"PGF_STYLE = {_python_literal(theme.constants['PGF_STYLE'])}",
        ]
    )

    helpers = _helper_source()
    kernel = runtime_kernel_source()
    screen = _screen_source()

    parts: list[str] = []
    if options.header_comment:
        parts.append(_header(graph, options, tokens, screen_size))
    parts.append(_init_python_block(kernel, -40))
    parts.append(_init_python_block(data_source, -35))
    parts.append(_init_python_block(helpers, -30))
    parts.append(theme.style_blocks + "\n")
    parts.append(_init_python_block(_label_callback_source(), 999))
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
        f"# Uninstall: delete every pgf_*.rpy file from the game directory.\n"
    )


def _helper_source() -> str:
    return '''\
def pgf_kernel():
    """Build a runtime state kernel over Ren'Py's persistent store."""
    return PGFKernel(
        PGFStore(persistent),
        PGF_ENTRY,
        [node[0] for node in PGF_NODES],
        PGF_ENDINGS,
        PGF_KERNEL_EDGES,
        label_map=PGF_LABEL_MAP,
        key="pgf_progress",
    )


def pgf_mark_label(name):
    try:
        pgf_kernel().mark_seen(name)
    except Exception:
        pass


def pgf_progress_text(kernel):
    summary = kernel.summary()
    total = len([node for node in PGF_NODES if node[1] != "ending"])
    return "已读 %d / %d    结局 %d / %d" % (
        summary.get("seen", 0),
        total,
        summary.get("ending_reached", 0),
        summary.get("ending_total", 0),
    )


def pgf_node_title(state, title):
    if state in ("locked", "ending_locked"):
        return "？？？"
    return title or "未命名"


def pgf_node_kind_label(kind, state):
    if kind == "choice":
        return "选择"
    if kind == "condition":
        return "分歧"
    if kind == "ending":
        return "结局"
    if kind == "entry":
        return "起点"
    return ""


def pgf_node_sensitive(state, label):
    return bool(label) and state not in ("locked", "ending_locked")


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


def pgf_jump_to(label):
    """Leave the menu context and continue the story at ``label``."""
    if not label:
        return
    if not renpy.has_label(label):
        renpy.notify("PaperGalFlow: 找不到剧情标签 %s" % label)
        return
    renpy.hide_screen("pgf_flowchart")
    if renpy.context_nesting_level() > 0:
        renpy.jump_out_of_context(label)
    else:
        renpy.jump(label)
'''


def _label_callback_source() -> str:
    return '''\
def _pgf_label_callback(name, abnormal):
    pgf_mark_label(name)


if hasattr(config, "label_callbacks"):
    if _pgf_label_callback not in config.label_callbacks:
        config.label_callbacks.append(_pgf_label_callback)
else:  # older Ren'Py
    _pgf_previous_label_callback = getattr(config, "label_callback", None)

    def _pgf_label_callback_wrapper(name, abnormal):
        _pgf_label_callback(name, abnormal)
        if _pgf_previous_label_callback:
            _pgf_previous_label_callback(name, abnormal)

    config.label_callback = _pgf_label_callback_wrapper
'''


def _screen_source() -> str:
    return """\
screen pgf_flowchart():
    modal True
    zorder 200

    default pgf_zoom = PGF_DEFAULT_ZOOM
    default pgf_state_kernel = pgf_kernel()
    default pgf_states = pgf_state_kernel.states()
    default pgf_progress = pgf_progress_text(pgf_state_kernel)
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

    add Solid(PGF_STYLE["colors"]["panel"]):
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
        background Solid(PGF_STYLE["colors"]["button_fill"])
        hover_background Solid(PGF_STYLE["colors"]["button_hover"])
        action SetScreenVariable("pgf_zoom", max(0.35, pgf_zoom - 0.1))
        text "－":
            style "pgf_chrome_text"
            xalign 0.5
            yalign 0.5

    button:
        xpos (_pgf_screen_w - 260)
        ypos _pgf_button_y
        xysize (46, 40)
        background Solid(PGF_STYLE["colors"]["button_fill"])
        hover_background Solid(PGF_STYLE["colors"]["button_hover"])
        action SetScreenVariable("pgf_zoom", min(2.0, pgf_zoom + 0.1))
        text "＋":
            style "pgf_chrome_text"
            xalign 0.5
            yalign 0.5

    button:
        xpos (_pgf_screen_w - 204)
        ypos _pgf_button_y
        xysize (78, 40)
        background Solid(PGF_STYLE["colors"]["button_fill"])
        hover_background Solid(PGF_STYLE["colors"]["button_hover"])
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
        background Solid(PGF_STYLE["colors"]["button_fill"])
        hover_background Solid(PGF_STYLE["colors"]["button_hover"])
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
                        background Solid(PGF_STYLE["colors"]["panel"])
                        padding (7, 2)
                        text _pgf_label[0]:
                            style "pgf_edge_text"

                for _pgf_node in PGF_NODES:
                    $ _pgf_state = pgf_states.get(_pgf_node[0], "locked")
                    $ _pgf_pal = PGF_STYLE["palettes"][pgf_palette_key(_pgf_state, _pgf_node[1])]

                    add Solid(PGF_STYLE["colors"]["shadow"]):
                        xpos (_pgf_node[5] + 5)
                        ypos (_pgf_node[6] + 6)
                        xysize (_pgf_node[7], _pgf_node[8])

                    button:
                        xpos _pgf_node[5]
                        ypos _pgf_node[6]
                        xysize (_pgf_node[7], _pgf_node[8])
                        background Solid(_pgf_pal["fill"])
                        hover_background Solid(_pgf_pal["hover"])
                        insensitive_background Solid(_pgf_pal["fill"])
                        sensitive pgf_node_sensitive(_pgf_state, _pgf_node[4])
                        action Function(pgf_jump_to, _pgf_node[4])
                        hovered SetScreenVariable("pgf_hover", pgf_node_title(_pgf_state, _pgf_node[2]))
                        unhovered SetScreenVariable("pgf_hover", "")

                        fixed:
                            xysize (_pgf_node[7], _pgf_node[8])

                            add Solid(_pgf_pal["border"]):
                                xpos 0
                                ypos 0
                                xysize (_pgf_node[7], 2)

                            add Solid(_pgf_pal["border"]):
                                xpos 0
                                ypos (_pgf_node[8] - 2)
                                xysize (_pgf_node[7], 2)

                            add Solid(_pgf_pal["border"]):
                                xpos 0
                                ypos 0
                                xysize (2, _pgf_node[8])

                            add Solid(_pgf_pal["border"]):
                                xpos (_pgf_node[7] - 2)
                                ypos 0
                                xysize (2, _pgf_node[8])

                            add Solid(_pgf_pal["strip"]):
                                xpos 0
                                ypos 0
                                xysize (6, _pgf_node[8])

                            text pgf_node_title(_pgf_state, _pgf_node[2]):
                                style "pgf_node_text"
                                color _pgf_pal["text"]
                                xpos 16
                                ypos 10
                                xsize (_pgf_node[7] - 30)
                                line_spacing 2

                            text pgf_node_kind_label(_pgf_node[1], _pgf_state):
                                style "pgf_small_text"
                                color _pgf_pal["strip"]
                                xpos 16
                                ypos (_pgf_node[8] - 26)

    add Solid(PGF_STYLE["colors"]["panel"]):
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
                add Solid(_pgf_legend_item[0]):
                    xysize (16, 16)
                    yalign 0.5
                text _pgf_legend_item[1]:
                    style "pgf_legend_text"
                    yalign 0.5

    text ("拖拽 / 滚轮浏览 · 点击已解锁节点跳转" if not pgf_hover else pgf_hover):
        style "pgf_small_text"
        xpos (_pgf_screen_w // 2)
        xanchor 0.5
        ypos (_pgf_footer_y + 22)

    button:
        xpos (_pgf_screen_w - 182)
        ypos (_pgf_footer_y + 14)
        xysize (38, 38)
        background Solid(PGF_STYLE["colors"]["button_fill"])
        hover_background Solid(PGF_STYLE["colors"]["button_hover"])
        action Function(pgf_scroll, pgf_yadj, -280)
        text "↑":
            style "pgf_chrome_text"
            xalign 0.5
            yalign 0.5

    button:
        xpos (_pgf_screen_w - 138)
        ypos (_pgf_footer_y + 14)
        xysize (38, 38)
        background Solid(PGF_STYLE["colors"]["button_fill"])
        hover_background Solid(PGF_STYLE["colors"]["button_hover"])
        action Function(pgf_scroll, pgf_yadj, 280)
        text "↓":
            style "pgf_chrome_text"
            xalign 0.5
            yalign 0.5

    button:
        xpos (_pgf_screen_w - 94)
        ypos (_pgf_footer_y + 14)
        xysize (38, 38)
        background Solid(PGF_STYLE["colors"]["button_fill"])
        hover_background Solid(PGF_STYLE["colors"]["button_hover"])
        action Function(pgf_scroll, pgf_xadj, -360)
        text "←":
            style "pgf_chrome_text"
            xalign 0.5
            yalign 0.5

    button:
        xpos (_pgf_screen_w - 50)
        ypos (_pgf_footer_y + 14)
        xysize (38, 38)
        background Solid(PGF_STYLE["colors"]["button_fill"])
        hover_background Solid(PGF_STYLE["colors"]["button_hover"])
        action Function(pgf_scroll, pgf_xadj, 360)
        text "→":
            style "pgf_chrome_text"
            xalign 0.5
            yalign 0.5

    key "game_menu" action Return()
"""
