"""T11 — o cliente durável é testado de verdade, em Node (sem navegador).

Um teste que só procura texto no JavaScript não provaria idempotência nem retomada. Este roda a
suíte do próprio módulo com o test runner do Node; se o Node não estiver disponível, o teste é
pulado explicitamente (nunca "verde por omissão").
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.skipif(shutil.which("node") is None, reason="node não está disponível")
def test_cliente_duravel_passa_na_suite_node() -> None:
    resultado = subprocess.run(
        ["node", "--test", "tests/js/durable.test.mjs"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert resultado.returncode == 0, resultado.stdout + resultado.stderr
    assert "# fail 0" in resultado.stdout


@pytest.mark.skipif(shutil.which("node") is None, reason="node não está disponível")
def test_app_e_durable_tem_sintaxe_valida() -> None:
    for arquivo in ("web/ui/scripts/app.js", "web/ui/scripts/durable.js"):
        resultado = subprocess.run(
            ["node", "--check", arquivo],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=60,
        )
        assert resultado.returncode == 0, f"{arquivo}: {resultado.stderr}"
