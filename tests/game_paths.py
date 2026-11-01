"""Locations of the two Ren'Py games used for integration testing.

The tests skip themselves when the games are not present, so the suite still
runs on machines without Steam.  Override with ``PGF_GAME1_DIR`` / ``PGF_GAME2_DIR``.
"""

from __future__ import annotations

import os
from pathlib import Path

_STEAM = Path.home() / ".local/share/Steam/steamapps/common"

GAME1_DEFAULT = _STEAM / "永恒与星辰与日常"
GAME2_DEFAULT = _STEAM / "小小的身影，重叠的内心"


def game1_dir() -> Path:
    return Path(os.environ.get("PGF_GAME1_DIR", GAME1_DEFAULT))


def game2_dir() -> Path:
    return Path(os.environ.get("PGF_GAME2_DIR", GAME2_DEFAULT))


def has_game1() -> bool:
    return (game1_dir() / "game").is_dir()


def has_game2() -> bool:
    return (game2_dir() / "game").is_dir()


__all__ = ["game1_dir", "game2_dir", "has_game1", "has_game2"]
