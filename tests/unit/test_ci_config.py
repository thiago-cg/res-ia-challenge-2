from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github" / "workflows" / "ci.yml"


def _workflow() -> dict:
    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))


def test_required_jobs_exist() -> None:
    jobs = _workflow()["jobs"]
    assert {"lint", "typecheck", "test", "integration"} <= set(jobs)


def test_python_and_uv_pinned() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "astral-sh/setup-uv@v6" in text
    assert '"3.12"' in text
    assert "uv sync --extra dev" in text


def test_qdrant_image_pinned() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "qdrant/qdrant:v1.15.3" in text
    assert "pgvector/pgvector:pg17" in text


def test_lint_and_typecheck_commands() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "ruff check ." in text
    assert "ruff format --check ." in text
    assert "mypy src" in text


def test_unit_and_integration_commands() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    assert 'pytest -m "not integration"' in text
    assert "apply_migrations.py" in text
    assert "pytest -m integration" in text


def test_ruff_config_is_not_duplicated() -> None:
    assert not (ROOT / "ruff.toml").exists()
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert "[tool.ruff]" in pyproject
