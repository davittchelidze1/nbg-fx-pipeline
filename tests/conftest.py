import json
from pathlib import Path

import pytest

from pipeline import transform

FIXTURES = Path(__file__).parent / "fixtures"


def load_payload(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


@pytest.fixture
def payload_fri():
    """Rates valid Saturday 2026-10-10 (published Friday, cover the weekend and Monday)."""
    return load_payload("nbg_2026-10-10.json")


@pytest.fixture
def payload_tue():
    """Rates valid Tuesday 2026-10-13, the next set after the weekend."""
    return load_payload("nbg_2026-10-13.json")


@pytest.fixture
def rows_fri(payload_fri):
    return transform.to_rows(payload_fri)


@pytest.fixture
def rows_tue(payload_tue):
    return transform.to_rows(payload_tue)
