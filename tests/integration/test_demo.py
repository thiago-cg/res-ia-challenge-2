"""T18 — a demonstração é reproduzível e executável (integração)."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.integration
def test_demo_duravel_roda_do_inicio_ao_fim() -> None:
    dsn = os.environ.get("TEST_DATABASE_URL")
    if not dsn:
        pytest.skip("Postgres not reachable; set TEST_DATABASE_URL")

    ambiente = {**os.environ, "DATABASE_URL": dsn, "PYTHONIOENCODING": "utf-8"}
    resultado = subprocess.run(
        [sys.executable, "scripts/demo_duravel.py"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=120,
        env=ambiente,
    )
    assert resultado.returncode == 0, resultado.stdout + resultado.stderr
    assert "202" in resultado.stdout  # aceitação
    assert "mesmo run: True" in resultado.stdout  # idempotência
    assert "run.completed" in resultado.stdout  # publicação
    assert "demonstração concluída" in resultado.stdout
