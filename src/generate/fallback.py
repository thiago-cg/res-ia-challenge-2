from collections.abc import Sequence
from typing import cast

from src.contracts import Answer, Citation, RetrievedDevice, VigenciaStatus

MIN_SCORE = 0.0

SAFE_ABSTENTION_MESSAGE = """\
Não encontrei base suficiente na minha base para responder com segurança.
Isso não significa que você não tenha direito; significa que eu não tenho a
fonte adequada para afirmar.

Posso te encaminhar para:
- Defensoria Pública do seu estado;
- Central de Atendimento à Mulher — 180;
- Delegacia Especializada no Atendimento à Mulher (DEAM), se houver na sua cidade."""

GUIDANCE_STEPS = [
    "Procurar a Defensoria Pública do seu estado.",
    "Ligar para a Central de Atendimento à Mulher — 180.",
    "Procurar a DEAM, se houver na sua cidade.",
]

GUIDANCE_REFERRALS = [
    {
        "tipo": "defensoria",
        "descricao": "A Defensoria Pública do seu estado pode orientar e acompanhar o caso.",
    },
    {
        "tipo": "central_mulher",
        "descricao": "A Central de Atendimento à Mulher atende pelo 180, 24 horas.",
    },
    {
        "tipo": "deam",
        "descricao": "A DEAM pode registrar a ocorrência, se houver na sua cidade.",
    },
]


def insufficient_evidence(
    retrieved: Sequence[RetrievedDevice] | None,
    min_score: float = MIN_SCORE,
) -> bool:
    if not retrieved:
        return True
    return not any(device.score >= min_score for device in retrieved)


def abstain(
    reason: str,
    *,
    retrieved: Sequence[RetrievedDevice] | None = None,
    data_atualizacao: str | None = None,
) -> Answer:
    message = SAFE_ABSTENTION_MESSAGE
    if data_atualizacao:
        message = f"{message}\n\nA base foi atualizada em {data_atualizacao}."

    return Answer(
        resposta=message,
        citacoes=[],
        proximos_passos=list(GUIDANCE_STEPS),
        encaminhamentos=[dict(item) for item in GUIDANCE_REFERRALS],
        premissas=[],
        nivel_confianca="baixo",
        abstencao=True,
        motivo_abstencao=reason,
    )


def _citation_from_retrieved(device: RetrievedDevice) -> Citation:
    vigencia = getattr(device, "vigencia", "vigente")
    if vigencia not in ("vigente", "alterado", "revogado", "cancelado", "superado"):
        vigencia = "vigente"

    return Citation(
        device_id=device.device_id,
        norm_version_id=device.norm_version_id,
        citacao=device.citacao,
        texto=device.texto_literal,
        contexto=str(getattr(device, "contexto", "")),
        vigencia=cast(VigenciaStatus, vigencia),
        fonte_url=str(getattr(device, "fonte_url", "")),
    )


def build_safe_answer(
    retrieved: Sequence[RetrievedDevice] | None,
    reason: str,
    *,
    min_score: float = MIN_SCORE,
) -> Answer:
    if insufficient_evidence(retrieved, min_score=min_score):
        return abstain(reason, retrieved=retrieved)

    devices = [device for device in retrieved or [] if device.score >= min_score]
    citations = [_citation_from_retrieved(device) for device in devices]

    return Answer(
        resposta=(
            "Não consegui gerar uma resposta com segurança agora. "
            "Encontrei estes dispositivos recuperados na base, que podem ajudar a orientar você. "
            "Confira as citações abaixo e procure orientação jurídica individual."
        ),
        citacoes=citations,
        proximos_passos=list(GUIDANCE_STEPS),
        encaminhamentos=[dict(item) for item in GUIDANCE_REFERRALS],
        premissas=["Nenhuma resposta foi gerada; exibindo apenas os dispositivos recuperados."],
        nivel_confianca="baixo",
        abstencao=True,
        motivo_abstencao=reason,
    )
