"""Which commit `/health` reports: env var, Railway's sha, the VERSION file written by deploy.sh, else dev."""

from __future__ import annotations

from pathlib import Path

import pytest

from app import main

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def clean_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    monkeypatch.delenv("GIT_SHA", raising=False)
    monkeypatch.delenv("RAILWAY_GIT_COMMIT_SHA", raising=False)
    monkeypatch.delenv("RENDER_GIT_COMMIT", raising=False)
    path = tmp_path / "VERSION"
    monkeypatch.setattr(main, "VERSION_FILE", path)
    return path


def test_git_sha_env_wins(monkeypatch: pytest.MonkeyPatch, clean_env: Path) -> None:
    clean_env.write_text("fromfile\n")
    monkeypatch.setenv("GIT_SHA", "abc1234")
    monkeypatch.setenv("RAILWAY_GIT_COMMIT_SHA", "railway")
    assert main.version() == "abc1234"


def test_the_docker_default_dev_does_not_hide_railways_sha(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GIT_SHA", "dev")  # the Dockerfile's ARG default
    monkeypatch.setenv("RAILWAY_GIT_COMMIT_SHA", "9f8e7d6")
    assert main.version() == "9f8e7d6"


def test_the_version_file_written_by_the_deploy_script_is_used(
    clean_env: Path,
) -> None:
    clean_env.write_text("0123456789abcdef\n", encoding="utf-8")
    assert main.version() == "0123456789abcdef"


def test_without_any_source_the_version_is_dev() -> None:
    assert main.version() == "dev"


def test_an_empty_version_file_means_dev(clean_env: Path) -> None:
    clean_env.write_text("\n")
    assert main.version() == "dev"


def test_render_exposes_its_commit_too(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GIT_SHA", "dev")
    monkeypatch.setenv("RENDER_GIT_COMMIT", "abc9999")
    assert main.version() == "abc9999"
