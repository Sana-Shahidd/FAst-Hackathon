"""Shared pytest fixtures (docs/09_SETUP_TEST_DEMO.md §2).

`client` works from T-01. The rest are skeletons filled in by the task that first needs
them; until then they raise so no test can quietly pass against a stub.
"""

from __future__ import annotations

import sys
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

# `pytest.ini` is at the repo root while this file is in `tests/`, so a bare `pytest`
# (as CI runs it) has no repo root on `sys.path` and cannot import `app`.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.main import app


@pytest.fixture
def client() -> Iterator[TestClient]:
    """FastAPI TestClient over the real app (lifespan runs)."""
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def user() -> None:
    """Created + logged-in `it-<uuid>@subah.test` user, deleted in teardown."""
    raise NotImplementedError("F-01: test user fixture arrives with auth in T-04")


@pytest.fixture
def onboarded_user() -> None:
    """User with a profile, 5 interests, 2 favorite sources and 1 muted keyword."""
    raise NotImplementedError("F-02: onboarded user fixture arrives in T-05")


@pytest.fixture
def edition() -> None:
    """Edition generated with fake agent outputs and mocked feeds."""
    raise NotImplementedError("F-05: edition fixture arrives with the pipeline in T-06")


@pytest.fixture
def feeds_mock() -> None:
    """respx router serving `tests/fixtures/*.xml` instead of real feeds."""
    raise NotImplementedError("F-04: feeds_mock fixture arrives with feeds in T-03")


@pytest.fixture
def fake_agents() -> None:
    """Fixed CuratorOut/EditorOut/LearnerOut/ProfilerOut, or None to force fallbacks."""
    raise NotImplementedError("F-05: fake_agents fixture arrives with agents in T-02")
