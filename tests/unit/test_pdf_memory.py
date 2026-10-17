"""Small hosts (512 MB free plans) start Chromium per PDF instead of keeping it running."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from app import main
from app.services import pdf

pytestmark = pytest.mark.unit

REAL_START_ON_STARTUP = (
    pdf.start_on_startup
)  # conftest replaces it with a no-op for every test


def limit_file(tmp_path: Path, text: str, name: str = "memory.max") -> str:
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return str(path)


def test_the_container_memory_limit_is_read_from_cgroup_files(tmp_path: Path) -> None:
    assert pdf.memory_limit_bytes((limit_file(tmp_path, "536870912\n"),)) == 536870912


def test_unlimited_missing_or_unreadable_limits_mean_none(tmp_path: Path) -> None:
    assert pdf.memory_limit_bytes((limit_file(tmp_path, "max\n"),)) is None
    assert pdf.memory_limit_bytes((str(tmp_path / "nope"),)) is None
    assert pdf.memory_limit_bytes(()) is None


def test_the_first_readable_file_wins_and_v1_works_too(tmp_path: Path) -> None:
    v2 = str(tmp_path / "absent")
    v1 = limit_file(tmp_path, "268435456", "limit_in_bytes")
    assert pdf.memory_limit_bytes((v2, v1)) == 268435456


@pytest.mark.parametrize(
    ("limit", "low"),
    [
        (512 * 1024**2, True),
        (1024**3 - 1, True),
        (1024**3, False),
        (16 * 1024**3, False),
        (None, False),
        (9223372036854771712, False),  # cgroup v1 "unlimited"
    ],
)
def test_under_one_gib_counts_as_low_memory(
    monkeypatch: pytest.MonkeyPatch, limit: int | None, low: bool
) -> None:
    monkeypatch.setattr(pdf, "memory_limit_bytes", lambda *a, **k: limit)
    assert pdf.low_memory() is low


async def test_a_low_memory_host_starts_no_browser_but_reports_the_pdf_engine_ready(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def boom() -> None:
        raise AssertionError("Chromium must not start at boot on a small host")

    monkeypatch.setattr(pdf, "low_memory", lambda: True)
    monkeypatch.setattr(pdf, "start_browser", boom)
    monkeypatch.setattr(pdf, "start_on_startup", REAL_START_ON_STARTUP)
    app = SimpleNamespace(state=SimpleNamespace())
    await pdf.start_on_startup(app)
    assert app.state.browser_on_demand is True
    assert await main.pdf_ok(app) is True


async def test_a_big_host_starts_the_shared_browser_at_boot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    started = []

    async def fake_start() -> None:
        started.append(True)
        pdf._browser = SimpleNamespace(is_connected=lambda: True)

    monkeypatch.setattr(pdf, "low_memory", lambda: False)
    monkeypatch.setattr(pdf, "start_browser", fake_start)
    monkeypatch.setattr(pdf, "start_on_startup", REAL_START_ON_STARTUP)
    app = SimpleNamespace(state=SimpleNamespace())
    try:
        await pdf.start_on_startup(app)
        assert started == [True] and await main.pdf_ok(app) is True
    finally:
        pdf._browser = None


async def test_without_any_browser_the_pdf_engine_is_not_ready() -> None:
    assert await main.pdf_ok(SimpleNamespace(state=SimpleNamespace())) is False
