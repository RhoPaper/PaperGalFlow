"""Read Ren'Py ``.rpa`` archives with nothing but the standard library.

Ren'Py archives are a header line, a zlib compressed pickle index and then the
raw file payloads.  Two flavours matter today:

* ``RPA-3.0 <offset> <key>`` -- payload offsets and lengths are XOR-ed with a
  32 bit key; every entry may carry a literal prefix (``start``) that is
  prepended to the payload.  ``RPA-3.2`` uses the same layout.
* ``RPA-2.0 <offset>`` -- like 3.0 without the key.

Loading a pickle from a third party game is a security boundary, so the index
is unpickled with a whitelist: only plain containers are accepted.
"""

from __future__ import annotations

import collections
import copyreg
import io
import pickle
import zlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator

from pgf_core.errors import PgfError

__all__ = ["RpaError", "RpaEntry", "RpaArchive", "find_archives"]


class RpaError(PgfError):
    """The archive is missing, truncated or uses an unsupported format."""


@dataclass(frozen=True)
class RpaEntry:
    offset: int
    length: int
    start: bytes = b""


_ALLOWED_PICKLE_GLOBALS = {
    ("collections", "OrderedDict"),
    ("collections", "defaultdict"),
    ("copyreg", "_reconstructor"),
}


class _IndexUnpickler(pickle.Unpickler):
    """Unpickles the archive index while refusing arbitrary callables."""

    def find_class(self, module: str, name: str) -> Any:
        if (module, name) not in _ALLOWED_PICKLE_GLOBALS:
            raise pickle.UnpicklingError(
                f"refusing to load {module}.{name} from an archive index"
            )
        if module == "copyreg":
            return copyreg._reconstructor
        return getattr(collections, name)

    def persistent_load(self, pid: Any) -> Any:  # pragma: no cover - defensive
        raise pickle.UnpicklingError("persistent ids are not allowed in an index")


class RpaArchive:
    """Random access reader for one ``.rpa`` file."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.version = 0
        self.entries: dict[str, RpaEntry | list[RpaEntry]] = {}
        self._file: Any = None

    # -- lifecycle -----------------------------------------------------------
    @classmethod
    def open(cls, path: Path) -> "RpaArchive":
        archive = cls(path)
        try:
            archive._read_index()
        except RpaError:
            raise
        except (OSError, ValueError, zlib.error, pickle.UnpicklingError) as exc:
            raise RpaError(f"could not read archive {archive.path}: {exc}") from exc
        return archive

    def close(self) -> None:
        if self._file is not None:
            self._file.close()
            self._file = None

    def __enter__(self) -> "RpaArchive":
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    def __del__(self) -> None:  # pragma: no cover - best effort
        self.close()

    # -- index ---------------------------------------------------------------
    def _read_index(self) -> None:
        with open(self.path, "rb") as handle:
            header = handle.readline(64)
            parts = header.split()
            if not parts:
                raise RpaError("empty archive header")
            magic = parts[0].decode("ascii", "replace")
            if magic in ("RPA-3.0", "RPA-3.2"):
                self.version = 3
                offset = int(parts[1], 16)
                key = int(parts[2], 16)
            elif magic == "RPA-2.0":
                self.version = 2
                offset = int(parts[1], 16)
                key = 0
            else:
                raise RpaError(f"unsupported archive magic {magic!r}")

            size = self.path.stat().st_size
            if offset <= 0 or offset >= size:
                raise RpaError(f"index offset {offset} is outside the archive")
            handle.seek(offset)
            payload = handle.read()

        try:
            decompressed = zlib.decompress(payload)
        except zlib.error as exc:
            raise RpaError(f"corrupt archive index in {self.path}: {exc}") from exc
        try:
            index = _IndexUnpickler(io.BytesIO(decompressed)).load()
        except Exception as exc:
            raise RpaError(f"invalid archive index in {self.path}: {exc}") from exc
        if not isinstance(index, dict):
            raise RpaError("archive index is not a mapping")

        entries: dict[str, RpaEntry | list[RpaEntry]] = {}
        for name, raw_entries in index.items():
            if not isinstance(name, str):
                continue
            if isinstance(raw_entries, (list, tuple)) and raw_entries and isinstance(
                raw_entries[0], (list, tuple)
            ):
                chunk_list = list(raw_entries)
            else:
                chunk_list = [raw_entries]
            parsed: list[RpaEntry] = []
            for raw in chunk_list:
                if not isinstance(raw, (list, tuple)) or len(raw) < 2:
                    continue
                raw_offset, raw_length = int(raw[0]), int(raw[1])
                if self.version == 3:
                    raw_offset ^= key
                    raw_length ^= key
                start = raw[2] if len(raw) > 2 else b""
                if isinstance(start, str):
                    start = start.encode("latin-1")
                elif not isinstance(start, (bytes, bytearray)):
                    start = b""
                parsed.append(RpaEntry(raw_offset, raw_length, bytes(start)))
            if not parsed:
                continue
            entries[name] = parsed[0] if len(parsed) == 1 else parsed
        self.entries = entries

    # -- access --------------------------------------------------------------
    def names(self) -> tuple[str, ...]:
        return tuple(self.entries)

    def __contains__(self, name: str) -> bool:
        return name in self.entries

    def __len__(self) -> int:
        return len(self.entries)

    def __iter__(self) -> Iterator[str]:
        return iter(self.entries)

    def read(self, name: str) -> bytes:
        entry = self.entries.get(name)
        if entry is None:
            raise KeyError(name)
        parts = entry if isinstance(entry, list) else [entry]
        if self._file is None:
            self._file = open(self.path, "rb")
        chunks: list[bytes] = []
        for part in parts:
            if part.offset < 0 or part.length < 0:
                raise RpaError(f"negative entry bounds for {name!r}")
            self._file.seek(part.offset)
            payload = self._file.read(part.length)
            if len(payload) != part.length:
                raise RpaError(f"truncated payload for {name!r}")
            chunks.append(part.start + payload)
        return b"".join(chunks)


def find_archives(game_dir: Path) -> tuple[Path, ...]:
    """Return ``.rpa`` archives inside ``game_dir``, sorted by name."""

    game_dir = Path(game_dir)
    if not game_dir.is_dir():
        return ()
    return tuple(sorted(path for path in game_dir.glob("*.rpa") if path.is_file()))
