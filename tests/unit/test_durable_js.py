"""T11 — o cliente durável é testado de verdade, em Node (sem navegador).

Um teste que só procura texto no JavaScript não provaria idempotência nem retomada. Este roda a
suíte do próprio módulo com o test runner do Node; se o Node não estiver disponível, o teste é
pulado explicitamente (nunca "verde por omissão").
"""

from __future__ import annotations

import re
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
    # O reporter padrão do Node muda entre versões: TAP escreve "# fail 0", o
    # reporter spec escreve "ℹ fail 0". Exigir o marcador exato fazia o teste
    # passar aqui (Node 22) e falhar no CI (Node 20). O que importa é não haver
    # falha e haver teste de verdade — suíte vazia não conta como verde.
    assert re.search(r"^[ \t]*[#ℹ][ \t]*fail 0[ \t]*$", resultado.stdout, re.MULTILINE), (
        resultado.stdout
    )
    assert re.search(r"^[ \t]*[#ℹ][ \t]*pass [1-9]\d*[ \t]*$", resultado.stdout, re.MULTILINE), (
        resultado.stdout
    )


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
