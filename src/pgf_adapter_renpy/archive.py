"""Unified virtual file system over a Ren'Py ``game/`` directory.

Ren'Py games ship scripts as plain files, inside ``.rpa`` archives, or a mix of
both.  :class:`GameArchive` presents one namespace, applies Ren'Py's precedence
rules (disk wins over archive, ``.rpy`` wins over ``.rpyc``) and caches parsed
scripts.  Translation files live under ``tl/`` and are excluded by default:
they repeat dialogue and would otherwise duplicate the story graph.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from pgf_core.errors import PgfError

from .rpa import RpaArchive, RpaError, find_archives
from .rpy_text import parse_script
from .rpyc import RpycError, decode_rpyc
from .script_model import ScriptFile

__all__ = ["GameArchive", "ScriptUnit", "ArchiveError"]

_SCRIPT_SUFFIXES = (".rpyc", ".rpy")
_EXCLUDED_PREFIXES_DEFAULT = ("tl/", "cache/", "saves/")


class ArchiveError(PgfError):
    """The game directory could not be inspected."""


@dataclass(frozen=True)
class ScriptUnit:
    """One logical script: a ``.rpy`` when available, else its ``.rpyc``."""

    stem: str
    format: str  # "rpy" or "rpyc"
    name: str  # full posix name relative to game/
    origin: str  # "disk" or archive file name
    size: int = 0

    @property
    def is_source(self) -> bool:
        return self.format == "rpy"


class GameArchive:
    def __init__(
        self,
        game_dir: Path,
        *,
        use_archives: bool = True,
        exclude_prefixes: Iterable[str] = _EXCLUDED_PREFIXES_DEFAULT,
    ) -> None:
        self.game_dir = Path(game_dir)
        if not self.game_dir.is_dir():
            raise ArchiveError(f"not a Ren'Py game directory: {self.game_dir}")
        self.warnings: list[str] = []
        self._archives: list[RpaArchive] = []
        self._disk: dict[str, Path] = {}
        self._archive_files: dict[str, tuple[RpaArchive, str]] = {}
        self._units: tuple[ScriptUnit, ...] = ()
        self._cache: dict[str, ScriptFile] = {}
        self._excluded = tuple(str(prefix).replace("\\", "/") for prefix in exclude_prefixes)

        if use_archives:
            for path in find_archives(self.game_dir):
                try:
                    archive = RpaArchive.open(path)
                except RpaError as exc:
                    self.warnings.append(f"skipped archive {path.name}: {exc}")
                    continue
                self._archives.append(archive)
                for name in archive.names():
                    self._archive_files[name] = (archive, name)
        self._scan_disk()
        self._build_units()

    # -- lifecycle -----------------------------------------------------------
    @classmethod
    def open(cls, game_dir: Path, **kwargs: object) -> "GameArchive":
        return cls(game_dir, **kwargs)

    def close(self) -> None:
        for archive in self._archives:
            archive.close()
        self._archives.clear()
        self._cache.clear()

    def __enter__(self) -> "GameArchive":
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    # -- discovery -----------------------------------------------------------
    def _is_excluded(self, name: str) -> bool:
        normalized = name.replace("\\", "/")
        return any(normalized.startswith(prefix) for prefix in self._excluded)

    def _scan_disk(self) -> None:
        try:
            candidates = sorted(self.game_dir.rglob("*"))
        except OSError as exc:  # pragma: no cover - permission problems
            raise ArchiveError(f"could not scan {self.game_dir}: {exc}") from exc
        for path in candidates:
            if not path.is_file():
                continue
            if path.suffix not in _SCRIPT_SUFFIXES:
                continue
            relative = path.relative_to(self.game_dir).as_posix()
            if self._is_excluded(relative):
                continue
            self._disk[relative] = path

    def _build_units(self) -> None:
        candidates: dict[str, dict[str, tuple[str, str, int]]] = {}
        for name, path in self._disk.items():
            stem = name[: -len(Path(name).suffix)]
            fmt = Path(name).suffix.lstrip(".")
            candidates.setdefault(stem, {})[fmt] = ("disk", name, path.stat().st_size)
        for name, (archive, _raw_name) in self._archive_files.items():
            if self._is_excluded(name):
                continue
            suffix = Path(name).suffix
            if suffix not in _SCRIPT_SUFFIXES:
                continue
            stem = name[: -len(suffix)]
            fmt = suffix.lstrip(".")
            bucket = candidates.setdefault(stem, {})
            # A disk file of the same format always wins over the archive.
            if fmt not in bucket:
                entry = archive.entries.get(name)
                size = entry.length if entry is not None and not isinstance(entry, list) else 0
                bucket[fmt] = ("archive", name, size)

        units: list[ScriptUnit] = []
        for stem in sorted(candidates):
            bucket = candidates[stem]
            if "rpy" in bucket:
                origin, name, size = bucket["rpy"]
                units.append(ScriptUnit(stem, "rpy", name, origin, size))
            elif "rpyc" in bucket:
                origin, name, size = bucket["rpyc"]
                units.append(ScriptUnit(stem, "rpyc", name, origin, size))
        self._units = tuple(units)

    # -- access --------------------------------------------------------------
    def units(self) -> tuple[ScriptUnit, ...]:
        return self._units

    def __len__(self) -> int:
        return len(self._units)

    def read_unit(self, unit: ScriptUnit) -> bytes:
        if unit.origin == "disk":
            path = self._disk.get(unit.name)
            if path is None:
                raise ArchiveError(f"missing file {unit.name}")
            return path.read_bytes()
        entry = self._archive_files.get(unit.name)
        if entry is None:
            raise ArchiveError(f"missing archive entry {unit.name}")
        archive, raw_name = entry
        return archive.read(raw_name)

    def read(self, name: str) -> bytes:
        """Read any virtual file by name (disk first, then archives)."""

        path = self._disk.get(name)
        if path is not None:
            return path.read_bytes()
        entry = self._archive_files.get(name)
        if entry is not None:
            archive, raw_name = entry
            return archive.read(raw_name)
        # Disk files that were not script files are not indexed; try directly.
        direct = self.game_dir / name
        if direct.is_file():
            return direct.read_bytes()
        raise ArchiveError(f"virtual file not found: {name}")

    def exists(self, name: str) -> bool:
        return name in self._disk or name in self._archive_files or (self.game_dir / name).is_file()

    def parse_unit(self, unit: ScriptUnit) -> ScriptFile:
        cached = self._cache.get(unit.name)
        if cached is not None:
            return cached
        blob = self.read_unit(unit)
        try:
            if unit.format == "rpy":
                script = parse_script(blob.decode("utf-8-sig"), unit.name)
            else:
                script = decode_rpyc(blob, unit.name)
        except (RpycError, UnicodeDecodeError, ValueError) as exc:
            raise ArchiveError(f"could not parse {unit.name}: {exc}") from exc
        self._cache[unit.name] = script
        return script

    def parse_all(self) -> dict[str, ScriptFile]:
        """Parse every script unit; broken files are reported, never fatal."""

        result: dict[str, ScriptFile] = {}
        for unit in self._units:
            try:
                result[unit.stem] = self.parse_unit(unit)
            except ArchiveError as exc:
                self.warnings.append(str(exc))
        return result

    def find_script(self, stem_or_name: str) -> ScriptFile | None:
        wanted = stem_or_name
        for unit in self._units:
            if unit.stem == wanted or unit.name == wanted:
                try:
                    return self.parse_unit(unit)
                except ArchiveError as exc:
                    self.warnings.append(str(exc))
                    return None
        return None

    def screen_source(self, screen_name: str) -> tuple[str, ScriptFile] | None:
        """Return the raw source of a screen definition, if the game has it."""

        for unit in self._units:
            if not unit.is_source:
                continue
            script = self.find_script(unit.stem)
            if script is None:
                continue
            info = script.screens().get(screen_name)
            if info is not None and info.source:
                return info.source, script
        return None
