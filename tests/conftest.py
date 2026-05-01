from pathlib import Path

import pytest

EXAMPLES = Path(__file__).resolve().parent.parent / "examples"


@pytest.fixture(scope="session")
def examples_dir() -> Path:
    return EXAMPLES
