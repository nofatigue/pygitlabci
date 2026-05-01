from __future__ import annotations

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
EXAMPLES = REPO_ROOT / "examples"


@pytest.fixture(scope="session")
def examples_dir() -> Path:
    return EXAMPLES
