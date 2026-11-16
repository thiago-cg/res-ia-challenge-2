"""Política de publicação (ADR-08, §21.6).

A regra global continua estrita: saída desconhecida é tratada como `juridica` e precisa de
evidência. Enfraquecer isto globalmente para permitir saudação é o que o ADR-08 proíbe.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from src.agents.contracts import RespostaConversa

#: Tipos que não podem carregar dispositivo nem afirmação jurídica.
TIPOS_SEM_CITACAO = frozenset({"esclarecimento", "social", "abstencao", "falha_tecnica"})


def dispositivos_evidenciados(evidencias: Sequence[Any]) -> set[str]:
    """Ids de dispositivo efetivamente presentes nas evidências da base."""

    ids: set[str] = set()
    for evidencia in evidencias or ():
        if isinstance(evidencia, dict) and evidencia.get("kind") == "base":
            device_id = evidencia.get("device_id")
            if isinstance(device_id, str) and device_id:
                ids.add(device_id)
    return ids


def validar_resposta(
    resposta: dict[str, Any] | None,
    evidencias: Sequence[Any],
    *,
    kind_esperado: str | None = None,
) -> list[str]:
    """Devolve a lista de problemas. Lista vazia significa publicável."""

    if not resposta:
        return ["resposta ausente"]

    try:
        texto = RespostaConversa.model_validate(resposta)
    except Exception as exc:  # noqa: BLE001 - o erro vira motivo, não traceback
        return [f"contrato inválido: {type(exc).__name__}"]

    problemas: list[str] = []
    if kind_esperado is not None and texto.kind != kind_esperado:
        problemas.append(f"kind {texto.kind!r} diverge do esperado {kind_esperado!r}")

    if texto.kind in TIPOS_SEM_CITACAO:
        return problemas

    # jurídica: todo device citado precisa estar nas evidências e ter sido hidratado
    evidenciados = dispositivos_evidenciados(evidencias)
    nao_evidenciados = [d for d in texto.device_ids if d not in evidenciados]
    if nao_evidenciados:
        problemas.append("dispositivo sem evidência: " + ", ".join(sorted(nao_evidenciados)))
    return problemas
