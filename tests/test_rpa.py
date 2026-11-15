from __future__ import annotations

import os
import pickle
import struct
import tempfile
import unittest
from unittest import mock
import zlib
from pathlib import Path

from pgf_adapter_renpy import rpa as rpa_module
from pgf_adapter_renpy.aes import aes256_ctr
from pgf_adapter_renpy.rpa import RpaArchive, RpaEncryptedError, RpaError, find_archives

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


def write_rpae(
    path: Path,
    files: dict[str, bytes],
    *,
    key: bytes,
    xor_key: int = 0x12345678,
) -> None:
    """Write a synthetic RPAE-2.0 archive for tests."""

    header = bytearray(52)
    header[0:8] = b"RPAE-2.0"
    header[8] = 0x20
    header[25] = 0x20
    header[34] = 0x0A
    index_nonce = bytes(range(12))
    header[40:52] = index_nonce
    offset = len(header)
    body = bytearray()
    index: dict[str, list[tuple[int, int, bytes]]] = {}
    for position, (name, data) in enumerate(files.items()):
        nonce = bytes([(position + 1) % 256] * 12)
        encrypted = aes256_ctr(key, nonce, data)
        start = offset + len(body)
        body.extend(encrypted)
        index[name] = [(start ^ xor_key, len(data) ^ xor_key, nonce)]
    index_offset = offset + len(body)
    header[9:25] = f"{index_offset:016x}".encode("ascii")
    header[26:34] = f"{xor_key:08x}".encode("ascii")
    compressed = zlib.compress(pickle.dumps(index, protocol=4))
    encrypted_index = aes256_ctr(key, index_nonce, compressed)
    path.write_bytes(bytes(header) + bytes(body) + encrypted_index)


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

    def test_rpae_roundtrip_with_key(self) -> None:
        key = bytes(range(32))
        files = {"scripts/script.rpyc": b"encrypted script", "gui/bg.png": b"PNG"}
        path = self.root / "encrypted.rpa"
        write_rpae(path, files, key=key)
        with RpaArchive.open(path, key=key.hex()) as archive:
            self.assertEqual(archive.version, 4)
            self.assertTrue(archive.encrypted)
            for name, data in files.items():
                self.assertEqual(archive.read(name), data)

    def test_rpae_requires_key(self) -> None:
        path = self.root / "encrypted.rpa"
        write_rpae(path, {"a": b"x"}, key=bytes(range(32)))
        with mock.patch.dict(os.environ, {"PGF_RPA_KEY": ""}):
            with self.assertRaises(RpaEncryptedError):
                RpaArchive.open(path)
        with self.assertRaises(RpaError):
            RpaArchive.open(path, key="not-a-key")

    def test_index_limits(self) -> None:
        compressed = zlib.compress(b"\x00" * 4096)
        with mock.patch.object(rpa_module, "MAX_INDEX_DECOMPRESSED", 1024):
            with self.assertRaises(RpaError):
                rpa_module._decompress_limited(compressed, 1024)
        path = self.root / "many.rpa"
        write_rpa(path, {f"f{i}.rpy": b"x" for i in range(5)})
        with mock.patch.object(rpa_module, "MAX_ENTRIES", 2):
            with self.assertRaises(RpaError):
                RpaArchive.open(path)

    def test_rpae_wrong_key_is_rejected(self) -> None:
        path = self.root / "encrypted.rpa"
        write_rpae(path, {"a": b"secret"}, key=bytes(range(32)))
        with self.assertRaises(RpaError):
            RpaArchive.open(path, key=(b"\x00" * 32).hex())

    def test_unsafe_names_and_oversized_entries_are_skipped(self) -> None:
        files = {"../evil.rpy": b"x", "/abs.rpy": b"x", "ok.rpy": b"ok"}
        path = self.root / "names.rpa"
        write_rpa(path, files)
        with RpaArchive.open(path) as archive:
            self.assertEqual(archive.names(), ("ok.rpy",))
            self.assertTrue(archive.warnings)

    def test_big_endian_slot_table(self) -> None:
        from pgf_adapter_renpy.rpyc import RPYC2_HEADER, extract_payload

        body = zlib.compress(pickle.dumps(({}, []), protocol=4))
        header = bytearray(RPYC2_HEADER)
        header.extend(b"\x00" * 24)
        start = len(header)
        header.extend(body)
        struct.pack_into(">III", header, len(RPYC2_HEADER), 2, start, len(body))
        self.assertEqual(extract_payload(bytes(header)), zlib.decompress(body))

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
