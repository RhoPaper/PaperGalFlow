#!/usr/bin/env python3
"""Development launcher for PaperGalFlow.

After ``pip install -e .`` the ``pgf`` console script is preferred.  This file
exists so the checkout can be used without installing: it puts ``src`` on the
path and registers the bundled Ren'Py adapter for this process only.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

SRC = Path(__file__).resolve().parent / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

os.environ.setdefault("PGF_ADAPTERS", "pgf_adapter_renpy.adapter:RenPyAdapter")

from pgf_core.cli import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
