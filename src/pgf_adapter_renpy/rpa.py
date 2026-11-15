"""Read Ren'Py ``.rpa`` archives with nothing but the standard library.

Ren'Py archives are a header line, a zlib compressed pickle index and then the
raw file payloads.  Supported flavours:

* ``RPA-3.0`` / ``RPA-3.2`` -- payload offsets and lengths are XOR-ed with a
  32 bit key; every entry may carry a literal prefix (``start``) that is
  prepended to the payload.
* ``RPA-2.0`` -- like 3.0 without the key.
* ``RPAE-2.0`` -- AES-256-CTR encrypted index and payloads.  The AES key is
  never stored in the archive; it must be supplied explicitly through
  ``PGF_RPA_KEY`` (64 hex characters) by a user who legally has it.

Loading a pickle from a third party game is a security boundary, so the index
is unpickled with a whitelist and every resource is bounded: index compression
ratio, entry count, name length, prefix length and per-file read size.
"""

from __future__ import annotations

import collections
import copyreg
import io
import os
import pickle
import zlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator

from pgf_core.errors import PgfError

from .aes import AesError, aes256_ctr

__all__ = [
    "RpaError",
    "RpaEncryptedError",
    "RpaEntry",
    "RpaArchive",
    "find_archives",
    "MAX_ENTRY_BYTES",
]

#: Hard limits for hostile archives.  Real Ren'Py archives are far below these.
MAX_INDEX_COMPRESSED = 64 * 1024 * 1024
MAX_INDEX_DECOMPRESSED = 128 * 1024 * 1024
MAX_ENTRIES = 200_000
MAX_NAME_BYTES = 4096
MAX_PREFIX_BYTES = 1024 * 1024
MAX_ENTRY_BYTES = 512 * 1024 * 1024
MAX_READ_BYTES = 512 * 1024 * 1024

_RPAE_HEADER = 52
_RPAE_NONCE = 12


class RpaError(PgfError):
    """The archive is missing, truncated or uses an unsupported format."""


class RpaEncryptedError(RpaError):
    """An RPAE archive needs a key that PaperGalFlow must not guess."""


@dataclass(frozen=True)
class RpaEntry:
    offset: int
    length: int
    start: bytes = b""
    nonce: bytes = b""

    @property
    def encrypted(self) -> bool:
        return bool(self.nonce)


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


def _decompress_limited(payload: bytes, limit: int) -> bytes:
    """Decompress a zlib stream without allowing a compression bomb."""

    decompressor = zlib.decompressobj()
    result = bytearray()
    try:
        chunk = decompressor.decompress(payload, limit + 1)
        result.extend(chunk)
        if len(result) > limit or decompressor.unconsumed_tail:
            raise RpaError("archive index exceeds the decompression limit")
        result.extend(decompressor.flush())
    except zlib.error as exc:
        raise RpaError(f"corrupt archive index: {exc}") from exc
    if len(result) > limit:
        raise RpaError("archive index exceeds the decompression limit")
    return bytes(result)


def _valid_name(name: str) -> bool:
    if not name or len(name.encode("utf-8", "replace")) > MAX_NAME_BYTES:
        return False
    if "\x00" in name or name.startswith("/") or "\\" in name:
        return False
    parts = name.split("/")
    return all(part not in ("", ".", "..") for part in parts)


def _parse_key(raw: str | bytes | None) -> bytes:
    if not raw:
        return b""
    if isinstance(raw, str):
        text = raw.strip()
        try:
            key = bytes.fromhex(text)
        except ValueError as exc:
            raise RpaError("PGF_RPA_KEY must be 64 hexadecimal characters") from exc
    else:
        key = bytes(raw)
    if len(key) != 32:
        raise RpaError("RPAE AES-256 key must be 32 bytes (64 hex characters)")
    return key


class RpaArchive:
    """Random access reader for one ``.rpa`` file."""

    def __init__(self, path: Path, *, key: str | bytes | None = None) -> None:
        self.path = Path(path)
        self.version = 0
        self.encrypted = False
        self.entries: dict[str, RpaEntry | list[RpaEntry]] = {}
        self.warnings: list[str] = []
        self._file: Any = None
        self._raw_key = key if key is not None else os.environ.get("PGF_RPA_KEY")
        self._key = b""

    # -- lifecycle -----------------------------------------------------------
    @classmethod
    def open(
        cls,
        path: Path,
        *,
        key: str | bytes | None = None,
    ) -> "RpaArchive":
        archive = cls(path, key=key)
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
        size = self.path.stat().st_size
        with open(self.path, "rb") as handle:
            prefix = handle.read(16)
            if prefix.startswith(b"RPAE-2.0"):
                self._read_rpae(handle, size)
                return
            handle.seek(0)
            header = handle.readline(64)
            parts = header.split()
            if not parts:
                raise RpaError("empty archive header")
            magic = parts[0].decode("ascii", "replace")
            if magic in ("RPA-3.0", "RPA-3.2"):
                self.version = 3
                if len(parts) < 3:
                    raise RpaError("RPA-3.x header is missing the key")
                offset = int(parts[1], 16)
                key = int(parts[2], 16)
            elif magic == "RPA-2.0":
                self.version = 2
                if len(parts) < 2:
                    raise RpaError("RPA-2.0 header is missing the index offset")
                offset = int(parts[1], 16)
                key = 0
            else:
                raise RpaError(f"unsupported archive magic {magic!r}")

            if offset <= 0 or offset >= size:
                raise RpaError(f"index offset {offset} is outside the archive")
            if size - offset > MAX_INDEX_COMPRESSED:
                raise RpaError("archive index exceeds the compressed size limit")
            handle.seek(offset)
            payload = handle.read()

        decompressed = _decompress_limited(payload, MAX_INDEX_DECOMPRESSED)
        index = self._load_index(decompressed)
        self._parse_index(index, key)

    def _read_rpae(self, handle: Any, size: int) -> None:
        handle.seek(0)
        header = handle.read(_RPAE_HEADER)
        if len(header) < _RPAE_HEADER or not header.startswith(b"RPAE-2.0"):
            raise RpaError("truncated RPAE-2.0 header")
        try:
            offset = int(header[9:25], 16)
            xor_key = int(header[26:34], 16)
        except ValueError as exc:
            raise RpaError("malformed RPAE-2.0 header") from exc
        nonce = header[40:52]
        if len(nonce) != _RPAE_NONCE:
            raise RpaError("malformed RPAE-2.0 index nonce")
        if offset <= _RPAE_HEADER or offset >= size:
            raise RpaError(f"RPAE index offset {offset} is outside the archive")
        if size - offset > MAX_INDEX_COMPRESSED:
            raise RpaError("RPAE index exceeds the compressed size limit")
        if not self._raw_key:
            raise RpaEncryptedError(
                "RPAE-2.0 archive requires an AES-256 key; set PGF_RPA_KEY "
                "to the 64-hex key (PaperGalFlow never embeds or guesses it)"
            )
        self._key = _parse_key(self._raw_key)
        handle.seek(offset)
        encrypted = handle.read()
        try:
            payload = aes256_ctr(self._key, nonce, encrypted)
        except AesError as exc:  # pragma: no cover - validated key length
            raise RpaError(str(exc)) from exc
        decompressed = _decompress_limited(payload, MAX_INDEX_DECOMPRESSED)
        index = self._load_index(decompressed)
        self.version = 4
        self.encrypted = True
        self._parse_index(index, xor_key)

    @staticmethod
    def _load_index(payload: bytes) -> dict[Any, Any]:
        try:
            index = _IndexUnpickler(io.BytesIO(payload)).load()
        except Exception as exc:
            raise RpaError(f"invalid archive index: {exc}") from exc
        if not isinstance(index, dict):
            raise RpaError("archive index is not a mapping")
        if len(index) > MAX_ENTRIES:
            raise RpaError("archive index has too many entries")
        return index

    def _parse_index(self, index: dict[Any, Any], xor_key: int) -> None:
        entries: dict[str, RpaEntry | list[RpaEntry]] = {}
        total_parts = 0
        for name, raw_entries in index.items():
            if not isinstance(name, str) or not _valid_name(name):
                self.warnings.append(f"skipped unsafe archive name {name!r}")
                continue
            if isinstance(raw_entries, (list, tuple)) and raw_entries and isinstance(
                raw_entries[0], (list, tuple)
            ):
                chunk_list = list(raw_entries)
            else:
                chunk_list = [raw_entries]
            parsed: list[RpaEntry] = []
            total_parts += len(chunk_list)
            if total_parts > MAX_ENTRIES:
                raise RpaError("archive index has too many entry parts")
            for raw in chunk_list:
                if not isinstance(raw, (list, tuple)) or len(raw) < 2:
                    self.warnings.append(f"skipped malformed entry for {name!r}")
                    continue
                try:
                    raw_offset, raw_length = int(raw[0]), int(raw[1])
                except (TypeError, ValueError):
                    self.warnings.append(f"skipped non-numeric entry for {name!r}")
                    continue
                if self.version in (3, 4):
                    raw_offset ^= xor_key
                    raw_length ^= xor_key
                start = raw[2] if len(raw) > 2 else b""
                nonce = b""
                if self.version == 4:
                    nonce = raw[2] if len(raw) > 2 else b""
                    start = b""
                    if isinstance(nonce, str):
                        nonce = nonce.encode("latin-1")
                    elif isinstance(nonce, (bytearray, memoryview)):
                        nonce = bytes(nonce)
                    if not isinstance(nonce, bytes) or len(nonce) != _RPAE_NONCE:
                        self.warnings.append(f"skipped entry with invalid nonce for {name!r}")
                        continue
                if isinstance(start, str):
                    start = start.encode("latin-1", "replace")
                elif isinstance(start, (bytearray, memoryview)):
                    start = bytes(start)
                elif not isinstance(start, bytes):
                    start = b""
                if raw_offset < 0 or raw_length < 0:
                    self.warnings.append(f"skipped negative entry bounds for {name!r}")
                    continue
                if raw_length > MAX_ENTRY_BYTES:
                    self.warnings.append(f"skipped oversized entry for {name!r}")
                    continue
                if len(start) > MAX_PREFIX_BYTES:
                    self.warnings.append(f"skipped oversized prefix for {name!r}")
                    continue
                parsed.append(RpaEntry(raw_offset, raw_length, start, nonce))
            if not parsed:
                continue
            if name in entries:
                self.warnings.append(f"duplicate archive entry {name!r}; keeping the last")
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
        total = 0
        for part in parts:
            if part.offset < 0 or part.length < 0:
                raise RpaError(f"negative entry bounds for {name!r}")
            if part.offset + part.length > self.path.stat().st_size:
                raise RpaError(f"entry for {name!r} points outside the archive")
            total += part.length + len(part.start)
            if total > MAX_READ_BYTES:
                raise RpaError(f"reading {name!r} would exceed the read limit")
            self._file.seek(part.offset)
            payload = self._file.read(part.length)
            if len(payload) != part.length:
                raise RpaError(f"truncated payload for {name!r}")
            if part.nonce:
                if not self._key:
                    self._key = _parse_key(self._raw_key)
                payload = aes256_ctr(self._key, part.nonce, payload)
            chunks.append(part.start + payload)
        return b"".join(chunks)


def find_archives(game_dir: Path) -> tuple[Path, ...]:
    """Return ``.rpa`` archives inside ``game_dir``, sorted by name."""

    game_dir = Path(game_dir)
    if not game_dir.is_dir():
        return ()
    return tuple(sorted(path for path in game_dir.glob("*.rpa") if path.is_file()))
