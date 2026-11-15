from __future__ import annotations

import unittest

from pgf_adapter_renpy.aes import AesError, aes256_ctr, aes256_encrypt_block, expand_key


class AesTests(unittest.TestCase):
    def test_fips197_aes256_vector(self) -> None:
        key = bytes.fromhex(
            "000102030405060708090a0b0c0d0e0f"
            "101112131415161718191a1b1c1d1e1f"
        )
        plaintext = bytes.fromhex("00112233445566778899aabbccddeeff")
        expected = bytes.fromhex("8ea2b7ca516745bfeafc49904b496089")
        self.assertEqual(aes256_encrypt_block(plaintext, expand_key(key)), expected)

    def test_ctr_roundtrip_and_counter(self) -> None:
        key = bytes(range(32))
        nonce = bytes(range(12))
        data = bytes(range(64))
        encrypted = aes256_ctr(key, nonce, data)
        self.assertNotEqual(encrypted, data)
        self.assertEqual(aes256_ctr(key, nonce, encrypted), data)
        # Counter changes the keystream.
        self.assertNotEqual(aes256_ctr(key, nonce, data, counter=1)[:16], encrypted[:16])

    def test_invalid_key_or_nonce(self) -> None:
        with self.assertRaises(AesError):
            expand_key(b"short")
        with self.assertRaises(AesError):
            aes256_ctr(b"x" * 32, b"short", b"data")


if __name__ == "__main__":
    unittest.main()
