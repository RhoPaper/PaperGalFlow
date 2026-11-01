"""Write generated files into a game, verify them and roll them back.

The installer owns only files whose names start with ``pgf_``.  It refuses to
overwrite a file it did not create unless ``force`` is given, keeps a manifest
with hashes so ``uninstall`` can detect user edits, and writes atomically.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from pgf_core.errors import PgfError
from pgf_core.version import __version__

from .screen_emit import GeneratedFile
from .rpy_text import parse_script

__all__ = [
    "InstallError",
    "InstallReport",
    "MANIFEST_NAME",
    "resolve_game_dir",
    "install_files",
    "uninstall_files",
    "read_manifest",
    "verify_install",
    "static_check",
]

MANIFEST_NAME = "pgf_manifest.json"
_NAME_RE = re.compile(r"^pgf_[A-Za-z0-9_.-]+\.rpy$")
_MARKER = "PaperGalFlow"


class InstallError(PgfError):
    """A file could not be installed safely."""


@dataclass
class InstallReport:
    game_dir: Path
    manifest_path: Path | None = None
    written: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    dry_run: bool = False

    @property
    def ok(self) -> bool:
        return not self.errors

    def summary(self) -> dict[str, object]:
        return {
            "game_dir": str(self.game_dir),
            "written": list(self.written),
            "skipped": list(self.skipped),
            "removed": list(self.removed),
            "warnings": list(self.warnings),
            "errors": list(self.errors),
            "dry_run": self.dry_run,
        }


def resolve_game_dir(path: Path) -> Path:
    """Accept either a Ren'Py base directory or its ``game/`` directory."""

    path = Path(path).expanduser().resolve()
    if (path / "game").is_dir() and not (path.name == "game"):
        return path / "game"
    if path.is_dir() and path.name == "game":
        return path
    if path.is_dir():
        return path
    raise InstallError(f"not a directory: {path}")


def _hash(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _has_marker(content: str) -> bool:
    return _MARKER in "\n".join(content.splitlines()[:8])


def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.chmod(temporary, 0o644)
        except OSError:  # pragma: no cover - Windows
            pass
        os.replace(temporary, path)
    except Exception:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise


def static_check(files: Iterable[GeneratedFile]) -> list[str]:
    """Cheap, dependency free sanity checks of generated sources."""

    problems: list[str] = []
    for generated in files:
        if not _NAME_RE.match(generated.name):
            problems.append(f"refusing unexpected generated file name: {generated.name}")
        if not generated.content.endswith("\n"):
            problems.append(f"{generated.name}: file does not end with a newline")
        try:
            script = parse_script(generated.content, generated.name)
        except Exception as exc:  # pragma: no cover - defensive
            problems.append(f"{generated.name}: could not parse generated source: {exc}")
            continue
        screens = script.screens()
        if generated.name == "pgf_flowchart_screen.rpy":
            if "pgf_flowchart" not in screens:
                problems.append("pgf_flowchart_screen.rpy does not define screen pgf_flowchart")
            if "PGF_NODES" not in generated.content:
                problems.append("pgf_flowchart_screen.rpy has no PGF_NODES data")
        if generated.name == "pgf_menu_hook.rpy":
            if 'ShowMenu("pgf_flowchart")' not in generated.content:
                problems.append("pgf_menu_hook.rpy never opens pgf_flowchart")
            if "quick_menu" not in screens and "pgf_quick_button" not in screens:
                problems.append("pgf_menu_hook.rpy has neither a quick menu patch nor an overlay button")
    return problems


def read_manifest(game_dir: Path) -> dict | None:
    path = resolve_game_dir(game_dir) / MANIFEST_NAME
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def install_files(
    game_dir: Path,
    files: Iterable[GeneratedFile],
    *,
    meta: dict[str, object] | None = None,
    force: bool = False,
    dry_run: bool = False,
) -> InstallReport:
    game_dir = resolve_game_dir(game_dir)
    report = InstallReport(game_dir=game_dir, dry_run=dry_run)
    generated = list(files)
    problems = static_check(generated)
    if problems:
        report.errors.extend(problems)
        return report
    if not game_dir.is_dir():
        report.errors.append(f"game directory does not exist: {game_dir}")
        return report

    old_manifest = read_manifest(game_dir) or {}
    old_names = {
        str(entry.get("name", ""))
        for entry in old_manifest.get("files", [])
        if isinstance(entry, dict)
    }
    new_names = {item.name for item in generated}

    for item in generated:
        target = game_dir / item.name
        if target.exists():
            existing = target.read_text(encoding="utf-8", errors="replace")
            if not _has_marker(existing) and not force:
                report.errors.append(
                    f"{item.name} exists and was not created by PaperGalFlow; "
                    "pass --force to overwrite it"
                )
                continue
        if dry_run:
            report.written.append(item.name)
            continue
        try:
            _atomic_write(target, item.content)
            report.written.append(item.name)
        except OSError as exc:
            report.errors.append(f"could not write {item.name}: {exc}")

    # Remove files from a previous install that are no longer generated.
    for stale in sorted(old_names - new_names):
        if not _NAME_RE.match(stale):
            continue
        target = game_dir / stale
        if not target.exists():
            continue
        try:
            content = target.read_text(encoding="utf-8", errors="replace")
            if not _has_marker(content) and not force:
                report.warnings.append(f"left stale file {stale} in place (missing marker)")
                continue
            if dry_run:
                report.removed.append(stale)
                continue
            target.unlink()
            report.removed.append(stale)
        except OSError as exc:
            report.errors.append(f"could not remove stale file {stale}: {exc}")

    if not report.errors and not dry_run:
        manifest = {
            "tool": "PaperGalFlow",
            "version": __version__,
            "created": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "files": [
                {
                    "name": item.name,
                    "role": item.role,
                    "sha256": _hash(item.content),
                    "bytes": item.byte_size,
                }
                for item in generated
            ],
            **(meta or {}),
        }
        manifest_path = game_dir / MANIFEST_NAME
        try:
            _atomic_write(manifest_path, json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
            report.manifest_path = manifest_path
        except OSError as exc:
            report.errors.append(f"could not write manifest: {exc}")
    return report


def uninstall_files(
    game_dir: Path,
    *,
    force: bool = False,
    dry_run: bool = False,
) -> InstallReport:
    game_dir = resolve_game_dir(game_dir)
    report = InstallReport(game_dir=game_dir, dry_run=dry_run)
    manifest = read_manifest(game_dir)
    names: set[str] = set()
    expected: dict[str, str] = {}
    if manifest:
        for entry in manifest.get("files", []):
            if not isinstance(entry, dict):
                continue
            name = str(entry.get("name", ""))
            if name:
                names.add(name)
                expected[name] = str(entry.get("sha256", ""))
    # Find orphans that still carry our marker.
    for path in sorted(game_dir.glob("pgf_*.rpy")):
        names.add(path.name)

    for name in sorted(names):
        if not _NAME_RE.match(name):
            continue
        companion = game_dir / (name[:-4] + ".rpyc")
        target = game_dir / name
        if not target.exists():
            report.skipped.append(name)
            continue
        try:
            content = target.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            report.errors.append(f"could not read {name}: {exc}")
            continue
        if not _has_marker(content) and not force:
            report.warnings.append(f"kept {name}: missing PaperGalFlow marker")
            continue
        digest = expected.get(name)
        if digest and _hash(content) != digest and not force:
            report.warnings.append(f"kept {name}: modified since install (use --force)")
            continue
        if dry_run:
            report.removed.append(name)
            continue
        try:
            target.unlink()
            report.removed.append(name)
                # Remove the compiled companion too, otherwise Ren'Py would keep
                # loading the old screen after the source is gone.
            if companion.is_file():
                try:
                    prefix = companion.read_bytes()[:10]
                except OSError:
                    prefix = b""
                if prefix.startswith(b"RENPY RPC2") or prefix[:2] == b"\x78\x9c":
                    companion.unlink()
                    report.removed.append(companion.name)
        except OSError as exc:
            report.errors.append(f"could not remove {name}: {exc}")

    manifest_path = game_dir / MANIFEST_NAME
    if manifest_path.exists():
        if dry_run:
            report.skipped.append(MANIFEST_NAME)
        else:
            try:
                manifest_path.unlink()
            except OSError as exc:
                report.errors.append(f"could not remove manifest: {exc}")
    if not report.errors:
        report.manifest_path = None if dry_run else manifest_path
    return report


def verify_install(game_dir: Path) -> list[str]:
    """Return a list of problems with an existing installation."""

    game_dir = resolve_game_dir(game_dir)
    manifest = read_manifest(game_dir)
    if not manifest:
        return ["no PaperGalFlow manifest found"]
    problems: list[str] = []
    for entry in manifest.get("files", []):
        if not isinstance(entry, dict):
            continue
        name = str(entry.get("name", ""))
        if not name:
            continue
        path = game_dir / name
        if not path.is_file():
            problems.append(f"missing file: {name}")
            continue
        content = path.read_text(encoding="utf-8", errors="replace")
        if not _has_marker(content):
            problems.append(f"{name} lost its PaperGalFlow marker")
        digest = str(entry.get("sha256", ""))
        if digest and _hash(content) != digest:
            problems.append(f"{name} was modified after installation")
    return problems
