from __future__ import annotations

import os
import pickle
import tempfile
import unittest
import zlib
from pathlib import Path

from pgf_adapter_renpy.rpa import RpaArchive, RpaError, find_archives

from .game_paths import game1_dir, has_game1


def _header(version: str, offset: int, key: int = 0) -> bytes:
    if version == "RPA-3.0":
        return f"RPA-3.0 {offset:016x} {key:08x}\n".encode()
    if version == "RPA-2.0":
        return f"RPA-2.0 {offset:016x}\n".encode()
    raise ValueError(version)


def write_rpa(
    path: Path,
    files: dict[str, bytes],
    version: str = "RPA-3.0",
    key: int = 0xDEADBEEF,
    prefixes: dict[str, bytes] | None = None,
) -> None:
    """Write a small, valid archive for tests."""

    probes = _header(version, 0, key)
    base = len(probes)
    body = bytearray()
    index: dict[str, list[tuple[int, int, bytes]]] = {}
    for name, data in files.items():
        offset = base + len(body)
        prefix = (prefixes or {}).get(name, b"")
        body.extend(data)
        if version == "RPA-3.0":
            index[name] = [(offset ^ key, len(data) ^ key, prefix)]
        else:
            index[name] = [(offset, len(data), prefix)]
    index_offset = base + len(body)
    header = _header(version, index_offset, key)
    assert len(header) == len(probes)
    compressed = zlib.compress(pickle.dumps(index, protocol=4))
    path.write_bytes(header + bytes(body) + compressed)


class SyntheticArchiveTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)

    def test_rpa3_roundtrip(self) -> None:
        files = {"a.txt": b"hello world", "dir/b.bin": bytes(range(256))}
        path = self.root / "test.rpa"
        write_rpa(path, files)
        with RpaArchive.open(path) as archive:
            self.assertEqual(archive.version, 3)
            self.assertEqual(set(archive.names()), set(files))
            for name, data in files.items():
                self.assertEqual(archive.read(name), data)
            self.assertIn("a.txt", archive)
            with self.assertRaises(KeyError):
                archive.read("missing.txt")

    def test_rpa2_roundtrip(self) -> None:
        files = {"x.rpyc": b"RENPY RPC2 payload"}
        path = self.root / "old.rpa"
        write_rpa(path, files, version="RPA-2.0")
        with RpaArchive.open(path) as archive:
            self.assertEqual(archive.version, 2)
            self.assertEqual(archive.read("x.rpyc"), files["x.rpyc"])

    def test_literal_prefix_is_prepended(self) -> None:
        files = {"f.bin": b"PAYLOAD"}
        path = self.root / "prefix.rpa"
        write_rpa(path, files, prefixes={"f.bin": b"PRE:"})
        with RpaArchive.open(path) as archive:
            self.assertEqual(archive.read("f.bin"), b"PRE:PAYLOAD")

    def test_missing_file(self) -> None:
        with self.assertRaises(RpaError):
            RpaArchive.open(self.root / "nope.rpa")

    def test_unsupported_magic(self) -> None:
        path = self.root / "bad.rpa"
        path.write_bytes(b"RPA-9.9 0000000000000010 00000000\njunk")
        with self.assertRaises(RpaError):
            RpaArchive.open(path)

    def test_index_pickle_cannot_reference_callables(self) -> None:
        payload = zlib.compress(pickle.dumps({"evil": os.system}, protocol=4))
        path = self.root / "evil.rpa"
        header = _header("RPA-2.0", 24) + b"\x00" * (24 - len(_header("RPA-2.0", 24)))
        path.write_bytes(header + payload)
        with self.assertRaises(RpaError):
            RpaArchive.open(path)

    def test_truncated_payload(self) -> None:
        files = {"a.txt": b"0123456789"}
        path = self.root / "trunc.rpa"
        write_rpa(path, files)
        data = path.read_bytes()
        # Remove bytes from the payload area, shifting the index but keeping
        # the (now stale) offsets in the index.
        path.write_bytes(data[: len(data) - 20])
        with self.assertRaises(RpaError):
            RpaArchive.open(path).read("a.txt")

    def test_find_archives(self) -> None:
        game = self.root / "game"
        game.mkdir()
        (game / "b.rpa").write_bytes(b"")
        (game / "a.rpa").write_bytes(b"")
        (game / "notes.txt").write_text("x")
        self.assertEqual(find_archives(game), (game / "a.rpa", game / "b.rpa"))


@unittest.skipUnless(has_game1(), "test game 1 is not installed")
class RealArchiveTests(unittest.TestCase):
    def test_real_scripts_archive(self) -> None:
        archives = find_archives(game1_dir() / "game")
        self.assertTrue(archives)
        scripts = game1_dir() / "game" / "scripts.rpa"
        self.assertTrue(scripts.is_file())
        with RpaArchive.open(scripts) as archive:
            self.assertGreater(len(archive), 10)
            self.assertIn("scripts/gui.rpyc", archive)
            self.assertTrue(archive.read("scripts/gui.rpyc").startswith(b"RENPY RPC2"))


if __name__ == "__main__":
    unittest.main()
