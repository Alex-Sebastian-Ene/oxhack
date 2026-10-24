"""Make the stand-alone scripts in experiments/ and coord/ importable from the tests.

    uv run --no-project --with pytest --with numpy --with scipy --with pandas pytest -q tests
"""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
for sub in ("experiments", "coord"):
    sys.path.insert(0, str(ROOT / sub))

BRENT = ROOT / "data" / "raw" / "DCOILBRENTEU.csv"
needs_brent = pytest.mark.skipif(not BRENT.exists(), reason="data/raw/DCOILBRENTEU.csv not downloaded")
