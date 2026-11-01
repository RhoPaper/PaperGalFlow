"""The ``pgf`` command line interface.

Everything in this module depends on :mod:`pgf_core` only; engine adapters are
loaded through the registry and never imported directly.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from .adapter import ChainReport, load_adapters
from .errors import PgfError
from .pipeline import Pipeline, PipelineOptions, PipelineReport, write_artifacts
from .preview import render_html
from .state import kernel_for_graph
from .version import __version__

_MARKS = {
    "success": "✓",
    "unavailable": "–",
    "failed": "✗",
    "skipped": "·",
}


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _print(message: str = "") -> None:
    print(message)


def _dump_json(payload: Any) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))


def _format_chain(chain: ChainReport) -> list[str]:
    lines = []
    for outcome in chain.outcomes:
        mark = _MARKS.get(outcome.status, "?")
        message = f" — {outcome.message}" if outcome.message else ""
        lines.append(f"  [{chain.name}] {outcome.step} {mark}{message}")
    return lines


def _print_report(report: PipelineReport, *, verbose: bool = True) -> None:
    info = report.info
    _print(f"PaperGalFlow v{__version__}")
    _print(f"  游戏    : {info.game_name}  ({info.engine} {info.engine_version})".rstrip())
    _print(f"  目录    : {info.game_dir}")
    if report.options.entry_label:
        _print(f"  入口标签: {report.options.entry_label} → {report.story.graph.entry}")
    if not verbose:
        return
    _print("  降级链:")
    for chain in report.chains.values():
        for line in _format_chain(chain):
            _print(line)
    stats = report.story.graph.stats()
    _print(
        "  图数据  : "
        f"{stats['nodes']} 节点, {stats['edges']} 连线, {stats['endings']} 结局; "
        f"布局 {report.layout.width}×{report.layout.height}"
    )
    tokens = report.style.tokens
    _print(
        f"  风格    : {getattr(tokens, 'name', '')} "
        f"({getattr(tokens, 'source', '')}, 置信度 {getattr(tokens, 'confidence', 0):.2f})"
    )
    _print(
        f"  入口    : {report.entry.mode} — {report.entry.reason} "
        f"(热键 {', '.join(report.entry.hotkey)})"
    )
    for warning in report.warnings:
        _print(f"  ⚠ {warning}")
    for note in report.notes[:8]:
        _print(f"  · {note}")
    if len(report.notes) > 8:
        _print(f"  · …另有 {len(report.notes) - 8} 条说明")


def _make_options(args: argparse.Namespace) -> PipelineOptions:
    return PipelineOptions(
        path=Path(args.path),
        adapter=getattr(args, "adapter", "") or "",
        entry_label=getattr(args, "entry", "start") or "start",
        include_side_labels=bool(getattr(args, "include_side_labels", False)),
        show_condition_labels=bool(getattr(args, "show_condition_labels", False)),
        style_preset=getattr(args, "preset", "paper_dark") or "paper_dark",
        entry_mode=getattr(args, "entry_mode", "") or "",
    )


def _run_pipeline(args: argparse.Namespace):
    registry = load_adapters()
    adapter = registry.get(getattr(args, "adapter", "") or "")
    pipeline = Pipeline(adapter, _make_options(args))
    try:
        report = pipeline.run()
    finally:
        close = getattr(adapter, "close", None)
        if callable(close):
            close()
    return report


def _install_meta(report: PipelineReport) -> dict[str, Any]:
    return {
        "entry_label": report.options.entry_label,
        "entry_node": report.story.graph.entry,
        "entry_mode": report.entry.mode,
        "style_source": getattr(report.style.tokens, "source", ""),
        "style_name": getattr(report.style.tokens, "name", ""),
        "story_source": report.story.source,
        "story_warnings": list(report.warnings),
    }


# ---------------------------------------------------------------------------
# commands
# ---------------------------------------------------------------------------


def _cmd_adapters(args: argparse.Namespace) -> int:
    registry = load_adapters()
    if args.json:
        _dump_json(
            {
                "adapters": [
                    {"name": name, "sources": registry.sources}
                    for name in registry.names()
                ]
            }
        )
        return 0
    if not len(registry):
        _print("没有注册任何适配器。安装本包或设置 PGF_ADAPTERS=module:Class。")
        return 1
    _print("已注册适配器:")
    for name in registry.names():
        adapter = registry.get(name)
        _print(f"  {name:10s} {getattr(adapter, 'engine', '')}")
    for source in registry.sources:
        _print(f"  · {source}")
    return 0


def _cmd_detect(args: argparse.Namespace) -> int:
    registry = load_adapters()
    adapter = registry.get(args.adapter or "")
    info = adapter.detect(Path(args.path))
    if info is None:
        if args.json:
            _dump_json({"detected": False, "path": str(Path(args.path).resolve())})
        else:
            _print(f"未识别的游戏目录: {Path(args.path).resolve()}")
        return 2
    payload = {
        "detected": True,
        "name": info.name,
        "engine": info.engine,
        "engine_version": info.engine_version,
        "game": info.game_name,
        "game_version": info.game_version,
        "basedir": str(info.base_dir),
        "game_dir": str(info.game_dir),
        "extra": info.extra,
    }
    if args.json:
        _dump_json(payload)
    else:
        _print(f"适配器 : {info.name} ({info.engine})")
        _print(f"游戏   : {info.game_name} {info.game_version}".rstrip())
        _print(f"引擎   : {info.engine_version}")
        _print(f"根目录 : {info.base_dir}")
        _print(f"game   : {info.game_dir}")
    return 0


def _cmd_inspect(args: argparse.Namespace) -> int:
    report = _run_pipeline(args)
    if args.json:
        _dump_json(report.summary())
    else:
        _print_report(report)
    return 0


def _cmd_build(args: argparse.Namespace) -> int:
    report = _run_pipeline(args)
    out_dir = Path(args.out)
    written = write_artifacts(out_dir, report.artifacts)
    if args.json:
        _dump_json(
            {
                "report": report.summary(),
                "written": [str(path) for path in written],
                "output": str(out_dir.resolve()),
            }
        )
    else:
        _print_report(report)
        _print()
        _print(f"已生成 {len(written)} 个文件到 {out_dir.resolve()}:")
        for path in written:
            _print(f"  · {path.name} ({path.stat().st_size} bytes)")
        _print("安装到游戏: pgf install <游戏目录>")
    return 0


def _cmd_install(args: argparse.Namespace) -> int:
    registry = load_adapters()
    adapter = registry.get(getattr(args, "adapter", "") or "")
    try:
        report = Pipeline(adapter, _make_options(args)).run()
        result = adapter.install(
            report.info,
            report.artifacts,
            meta=_install_meta(report),
            force=bool(args.force),
            dry_run=bool(args.dry_run),
        )
    finally:
        close = getattr(adapter, "close", None)
        if callable(close):
            close()
    if args.json:
        _dump_json({"report": report.summary(), "install": result.summary()})
    else:
        _print_report(report)
        _print()
        prefix = "将写入" if args.dry_run else "已写入"
        for name in result.written:
            _print(f"  {prefix}: {name}")
        for name in result.removed:
            _print(f"  {'将删除' if args.dry_run else '已删除'}: {name}")
        for warning in result.warnings:
            _print(f"  ⚠ {warning}")
        for error in result.errors:
            _print(f"  ✗ {error}")
        if result.ok:
            _print()
            _print(f"安装完成。回滚: pgf uninstall {report.info.base_dir}")
            _print("提示: 首次安装后建议用 Ren'Py 的 lint（例如 ./游戏启动脚本 . lint）确认无语法错误。")
    return 0 if result.ok else 1


def _cmd_uninstall(args: argparse.Namespace) -> int:
    registry = load_adapters()
    adapter = registry.get(getattr(args, "adapter", "") or "")
    info = adapter.detect(Path(args.path))
    if info is None:
        _print(f"未识别的游戏目录: {Path(args.path).resolve()}")
        return 2
    uninstall = getattr(adapter, "uninstall", None)
    if not callable(uninstall):
        _print("当前适配器不支持卸载。")
        return 1
    result = uninstall(info, force=bool(args.force), dry_run=bool(args.dry_run))
    if args.json:
        _dump_json({"game": info.game_name, "remove": result.summary()})
    else:
        for name in result.removed:
            _print(f"  {'将删除' if args.dry_run else '已删除'}: {name}")
        for name in result.skipped:
            _print(f"  跳过: {name}")
        for warning in result.warnings:
            _print(f"  ⚠ {warning}")
        for error in result.errors:
            _print(f"  ✗ {error}")
        if result.ok:
            _print("已回滚 PaperGalFlow 生成的文件。")
    return 0 if result.ok else 1


def _cmd_status(args: argparse.Namespace) -> int:
    registry = load_adapters()
    adapter = registry.get(getattr(args, "adapter", "") or "")
    info = adapter.detect(Path(args.path))
    if info is None:
        _print(f"未识别的游戏目录: {Path(args.path).resolve()}")
        return 2
    status_fn = getattr(adapter, "install_info", None)
    status = status_fn(info) if callable(status_fn) else {"installed": False}
    if args.json:
        _dump_json({"game": info.game_name, "basedir": str(info.base_dir), **status})
        return 0
    if not status.get("installed"):
        _print(f"{info.game_name}: 尚未安装 PaperGalFlow。")
        return 0
    _print(f"{info.game_name}: 已安装 PaperGalFlow {status.get('version', '')}")
    _print(f"  清单    : {status.get('manifest', '')}")
    _print(f"  入口    : {status.get('entry_mode', '')}")
    _print(f"  风格    : {status.get('style_source', '')}")
    _print(f"  文件    : {', '.join(status.get('files', []))}")
    problems = status.get("problems", [])
    if problems:
        for problem in problems:
            _print(f"  ⚠ {problem}")
    return 0


def _cmd_preview(args: argparse.Namespace) -> int:
    report = _run_pipeline(args)
    seen = [item.strip() for item in (args.seen or "").split(",") if item.strip()]
    kernel = kernel_for_graph(report.story.graph)
    for item in seen:
        kernel.mark_seen(item)
    states = kernel.states()
    title = args.title or report.info.game_name or "剧情流程图"
    content = render_html(
        report.story.graph,
        report.layout,
        report.style.tokens,
        title=title,
        subtitle=f"{report.entry.mode} · {getattr(report.style.tokens, 'name', '')}",
        states=states,
        show_condition_labels=report.options.show_condition_labels,
    )
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(content, encoding="utf-8", newline="\n")
    if args.json:
        _dump_json({"report": report.summary(), "preview": str(out.resolve())})
    else:
        _print_report(report, verbose=False)
        _print(f"预览已写入 {out.resolve()}")
    return 0


def _cmd_uninstall_doc(args: argparse.Namespace) -> int:  # pragma: no cover - alias
    return _cmd_uninstall(args)


# ---------------------------------------------------------------------------
# parser
# ---------------------------------------------------------------------------


def _add_common(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("path", help="Ren'Py 游戏根目录或 game/ 目录")
    parser.add_argument("--adapter", default="", help="指定适配器（默认自动选择）")
    parser.add_argument("--entry", default="start", help="入口 label（默认 start）")
    parser.add_argument("--preset", default="paper_dark", choices=("paper_dark", "paper_light"),
                        help="预置风格（证据不足时使用）")
    parser.add_argument("--entry-mode", default="",
                        choices=("", "quick_menu_patch", "ai_rewrite", "overlay_button"),
                        help="强制入口模式")
    parser.add_argument("--include-side-labels", action="store_true",
                        help="包含仅通过 call 到达的支线 label")
    parser.add_argument("--show-condition-labels", action="store_true",
                        help="在图上显示 if 条件表达式（默认隐藏，避免剧透）")
    parser.add_argument("--json", action="store_true", help="输出 JSON")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pgf",
        description="PaperGalFlow — 为 Galgame 生成柚子社式剧情流程图",
    )
    parser.add_argument("--version", action="version", version=f"PaperGalFlow {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("adapters", help="列出已注册的引擎适配器")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=_cmd_adapters)

    p = sub.add_parser("detect", help="识别游戏目录")
    p.add_argument("path")
    p.add_argument("--adapter", default="")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=_cmd_detect)

    p = sub.add_parser("inspect", help="解析剧情与风格，不写文件")
    _add_common(p)
    p.set_defaults(func=_cmd_inspect)

    p = sub.add_parser("build", help="生成 pgf_*.rpy 到输出目录")
    _add_common(p)
    p.add_argument("--out", default="out", help="输出目录（默认 out）")
    p.set_defaults(func=_cmd_build)

    p = sub.add_parser("install", help="生成并写入游戏目录")
    _add_common(p)
    p.add_argument("--force", action="store_true", help="覆盖同名但缺少 PaperGalFlow 标记的文件")
    p.add_argument("--dry-run", action="store_true", help="只显示计划，不写文件")
    p.set_defaults(func=_cmd_install)

    p = sub.add_parser("uninstall", help="删除 PaperGalFlow 生成的文件")
    p.add_argument("path")
    p.add_argument("--adapter", default="")
    p.add_argument("--force", action="store_true", help="即使文件被修改也删除")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=_cmd_uninstall)

    p = sub.add_parser("status", help="查看安装状态")
    p.add_argument("path")
    p.add_argument("--adapter", default="")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=_cmd_status)

    p = sub.add_parser("preview", help="生成离线 HTML 预览")
    _add_common(p)
    p.add_argument("--out", default="out/flowchart.html", help="输出 HTML 路径")
    p.add_argument("--title", default="", help="预览标题")
    p.add_argument("--seen", default="", help="逗号分隔的已读 node/label，用于预览状态")
    p.set_defaults(func=_cmd_preview)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except PgfError as exc:
        print(f"错误: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:  # pragma: no cover
        print("已取消。", file=sys.stderr)
        return 130


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
