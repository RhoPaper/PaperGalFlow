"""Host side preview of the generated flowchart (SVG / HTML).

This is a developer aid: it renders the exact layout and style tokens the game
will receive, without starting Ren'Py.  It is not used by the patched game.
"""

from __future__ import annotations

import html
from .layout import Layout
from .model import EdgeKind, FlowGraph, NodeKind
from .state import NodeState, kernel_for_graph

__all__ = ["render_svg", "render_html"]

_EDGE_VARS = {
    EdgeKind.FLOW: "flow",
    EdgeKind.CHOICE: "choice",
    EdgeKind.CONDITION: "condition",
    EdgeKind.CALL: "call",
    EdgeKind.END: "flow",
}


def _escape(text: str) -> str:
    return html.escape(text, quote=True)


def _wrap(text: str, width: int, limit: int = 3) -> list[str]:
    text = (text or "").strip()
    if not text:
        return []
    lines: list[str] = []
    current = ""
    for char in text:
        if char == "\n":
            lines.append(current)
            current = ""
            continue
        current += char
        if len(current) >= width:
            lines.append(current)
            current = ""
    if current:
        lines.append(current)
    if len(lines) > limit:
        lines = lines[:limit]
        lines[-1] = lines[-1][:-1] + "…"
    return lines


def _state_of(states: dict[str, str], node_id: str) -> str:
    return states.get(node_id, NodeState.LOCKED.value)


def _palette_key(state: str, kind: NodeKind) -> str:
    if state in (NodeState.ENDING_LOCKED.value, NodeState.ENDING_READ.value):
        return "ending"
    if state == NodeState.LOCKED.value:
        return "locked"
    if state == NodeState.READ.value:
        return "read"
    if kind is NodeKind.CHOICE:
        return "choice"
    if kind is NodeKind.CONDITION:
        return "condition"
    return "unread"


def _kind_label(kind: NodeKind) -> str:
    return {
        NodeKind.ENTRY: "起点",
        NodeKind.CHOICE: "选择",
        NodeKind.CONDITION: "分歧",
        NodeKind.ENDING: "结局",
    }.get(kind, "")


def render_svg(
    graph: FlowGraph,
    layout: Layout,
    tokens,
    *,
    states: dict[str, str] | None = None,
    show_condition_labels: bool = False,
    margin: int = 32,
) -> str:
    """Render the chart as a standalone SVG document."""

    if states is None:
        states = {node_id: value for node_id, value in kernel_for_graph(graph).states().items()}
    width = layout.width + margin * 2
    height = layout.height + margin * 2
    colors = tokens
    parts: list[str] = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}" font-family="\'Noto Sans CJK SC\', \'Microsoft YaHei\', \'PingFang SC\', sans-serif">',
        "<defs>",
    ]
    edge_colors = {
        "flow": tokens.edge,
        "choice": tokens.edge_choice,
        "condition": tokens.edge_condition,
        "call": tokens.edge_call,
    }
    for name, color in edge_colors.items():
        parts.append(
            f'<marker id="arrow-{name}" viewBox="0 0 10 10" refX="9" refY="5" '
            f'markerWidth="7" markerHeight="7" orient="auto-start-reverse">'
            f'<path d="M 0 0 L 10 5 L 0 10 z" fill="{color}"/></marker>'
        )
    parts.append("</defs>")
    parts.append(
        f'<rect x="0" y="0" width="{width}" height="{height}" fill="{tokens.background}"/>'
    )
    parts.append(f'<g transform="translate({margin},{margin})">')

    # edges
    for edge in layout.edges:
        variable = _EDGE_VARS.get(edge.kind, "flow")
        color = edge_colors[variable]
        points = " ".join(f"{point.x},{point.y}" for point in edge.points)
        dash = ' stroke-dasharray="10 7"' if edge.kind is EdgeKind.CALL else ""
        parts.append(
            f'<polyline points="{points}" fill="none" stroke="{color}" stroke-width="4" '
            f'stroke-linejoin="round" stroke-linecap="round"{dash} '
            f'marker-end="url(#arrow-{variable})"/>'
        )
    # edge labels
    for edge in layout.edges:
        if not edge.label:
            continue
        if edge.kind is EdgeKind.CONDITION and not show_condition_labels:
            continue
        x, y = edge.label_at.x, edge.label_at.y
        target = layout.positions.get(edge.target)
        if target is not None and edge.kind in (EdgeKind.CHOICE, EdgeKind.CONDITION):
            x = target.x + target.w // 2
            y = target.y - 20
        text = edge.label if len(edge.label) <= 26 else edge.label[:25] + "…"
        parts.append(
            f'<rect x="{x - max(10, len(text) * 8)}" y="{y - 13}" width="{max(20, len(text) * 16)}" '
            f'height="26" rx="5" fill="{tokens.panel}" opacity="0.92"/>'
        )
        parts.append(
            f'<text x="{x}" y="{y + 5}" font-size="{tokens.edge_text_size}" '
            f'fill="{tokens.text_dim}" text-anchor="middle">{_escape(text)}</text>'
        )

    # nodes
    for node in graph.nodes.values():
        rect = layout.positions.get(node.id)
        if rect is None:
            continue
        state = _state_of(states, node.id)
        palette = tokens.palette(_palette_key(state, node.kind))
        locked = state in (NodeState.LOCKED.value, NodeState.ENDING_LOCKED.value)
        title = "？？？" if locked else (node.title or node.subtitle or "未命名")
        parts.append(
            f'<rect x="{rect.x + 5}" y="{rect.y + 7}" width="{rect.w}" height="{rect.h}" '
            f'rx="8" fill="{tokens.shadow}" opacity="0.55"/>'
        )
        parts.append(
            f'<rect x="{rect.x}" y="{rect.y}" width="{rect.w}" height="{rect.h}" '
            f'rx="8" fill="{palette.fill}" stroke="{palette.border}" stroke-width="2"/>'
        )
        parts.append(
            f'<rect x="{rect.x}" y="{rect.y + 8}" width="6" height="{rect.h - 16}" '
            f'rx="3" fill="{palette.strip}"/>'
        )
        chars = max(6, int((rect.w - 30) / max(8.0, tokens.node_text_size * 0.86)))
        lines = _wrap(title, chars, 3)
        for index, line in enumerate(lines):
            parts.append(
                f'<text x="{rect.x + 16}" y="{rect.y + 28 + index * (tokens.node_text_size + 3)}" '
                f'font-size="{tokens.node_text_size}" fill="{palette.text}">{_escape(line)}</text>'
            )
        kind_label = _kind_label(node.kind)
        if kind_label:
            parts.append(
                f'<text x="{rect.x + 16}" y="{rect.y + rect.h - 12}" '
                f'font-size="{tokens.subtitle_size}" fill="{palette.strip}">{kind_label}</text>'
            )
    parts.append("</g>")
    parts.append("</svg>")
    return "\n".join(parts)


_CENTER_SCRIPT = """<script>
(function () {
  const canvas = document.querySelector('.canvas');
  const svg = document.querySelector('svg');
  if (canvas && svg) {
    canvas.scrollLeft = Math.max(0, svg.clientWidth / 2 - canvas.clientWidth / 2);
  }
})();
</script>"""


def render_html(
    graph: FlowGraph,
    layout: Layout,
    tokens,
    *,
    title: str = "剧情流程图",
    subtitle: str = "",
    states: dict[str, str] | None = None,
    show_condition_labels: bool = False,
) -> str:
    """Wrap :func:`render_svg` in a small, printable HTML page."""

    svg = render_svg(
        graph,
        layout,
        tokens,
        states=states,
        show_condition_labels=show_condition_labels,
    )
    stats = graph.stats()
    legend = [
        (tokens.palette("read").strip, "已读"),
        (tokens.palette("unread").strip, "未读"),
        (tokens.palette("locked").strip, "锁定"),
        (tokens.palette("ending").strip, "结局"),
    ]
    legend_html = "".join(
        f'<span class="legend"><i style="background:{color}"></i>{_escape(label)}</span>'
        for color, label in legend
    )
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<title>{_escape(title)} — PaperGalFlow 预览</title>
<style>
  :root {{ color-scheme: light dark; }}
  body {{ margin: 0; background: {tokens.background}; color: {tokens.text};
         font-family: "Noto Sans CJK SC", "Microsoft YaHei", "PingFang SC", sans-serif; }}
  header {{ display: flex; align-items: baseline; gap: 18px; flex-wrap: wrap;
            padding: 18px 26px; background: {tokens.panel}; border-bottom: 2px solid {tokens.border}; }}
  h1 {{ margin: 0; font-size: {tokens.title_size * 0.8:.0f}px; letter-spacing: 1px; }}
  .sub {{ color: {tokens.text_dim}; font-size: 15px; }}
  .legend {{ display: inline-flex; align-items: center; gap: 6px; margin-right: 16px;
             color: {tokens.text_dim}; font-size: 15px; }}
  .legend i {{ width: 14px; height: 14px; border-radius: 4px; display: inline-block; }}
  .canvas {{ overflow: auto; padding: 22px; }}
  svg {{ display: block; border-radius: 12px; }}
  footer {{ padding: 10px 26px 26px; color: {tokens.text_muted}; font-size: 13px; }}
</style>
</head>
<body>
<header>
  <h1>{_escape(title)}</h1>
  <span class="sub">{_escape(subtitle)}</span>
  <span class="sub">{stats['nodes']} 节点 · {stats['edges']} 连线 · {stats['endings']} 结局 · 风格 {_escape(getattr(tokens, 'name', ''))}</span>
  <span style="flex:1"></span>
  {legend_html}
</header>
<div class="canvas">
{svg}
</div>
<footer>由 PaperGalFlow 生成的离线预览。实际游戏内画面由 Ren'Py 渲染，可能与浏览器字体略有差异。</footer>
{_CENTER_SCRIPT}
</body>
</html>
"""
