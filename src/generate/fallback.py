import re
from collections.abc import Sequence
from typing import cast

from src.contracts import Answer, Citation, RetrievedDevice, VigenciaStatus

MIN_SCORE = 0.0
MAX_FALLBACK_DEVICES = 10

_ARTIGO_RE = re.compile(r"^(.*?/art[^/]+)")

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


def _artigo_id(device_id: str) -> str:
    match = _ARTIGO_RE.match(device_id)
    return match.group(1) if match else device_id


def _better_duplicate(candidate: RetrievedDevice, current: RetrievedDevice) -> bool:
    candidate_known = candidate.vigencia is not None
    current_known = current.vigencia is not None
    if candidate_known != current_known:
        return candidate_known
    return candidate.score > current.score


def _dedupe_by_artigo(devices: Sequence[RetrievedDevice]) -> list[RetrievedDevice]:
    best_by_artigo: dict[str, RetrievedDevice] = {}

    for device in devices:
        key = _artigo_id(device.device_id)
        current = best_by_artigo.get(key)
        if current is None or _better_duplicate(device, current):
            best_by_artigo[key] = device

    return list(best_by_artigo.values())


def _select_devices(
    retrieved: Sequence[RetrievedDevice] | None,
    min_score: float,
    max_devices: int,
) -> list[RetrievedDevice]:
    devices = list(retrieved or [])
    explicit = [device for device in devices if device.source == "explicit"]
    non_explicit = [
        device for device in devices if device.source != "explicit" and device.score > min_score
    ]

    explicit_selected = sorted(
        _dedupe_by_artigo(explicit), key=lambda device: device.score, reverse=True
    )[:max_devices]
    seen = {_artigo_id(device.device_id) for device in explicit_selected}

    non_explicit_selected = [
        device
        for device in _dedupe_by_artigo(non_explicit)
        if _artigo_id(device.device_id) not in seen
    ]
    non_explicit_selected.sort(key=lambda device: device.score, reverse=True)

    remaining = max(0, max_devices - len(explicit_selected))
    return explicit_selected + non_explicit_selected[:remaining]


def insufficient_evidence(
    retrieved: Sequence[RetrievedDevice] | None,
    min_score: float = MIN_SCORE,
) -> bool:
    if not retrieved:
        return True
    if any(device.source == "explicit" for device in retrieved):
        return False
    return not any(device.score > min_score for device in retrieved)


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
    if device.vigencia is None:
        raise ValueError("cannot build a citation without known vigência")

    return Citation(
        device_id=device.device_id,
        norm_version_id=device.norm_version_id,
        citacao=device.citacao,
        texto=device.texto_literal,
        contexto=device.contexto or "",
        vigencia=cast(VigenciaStatus, device.vigencia),
        fonte_url=str(getattr(device, "fonte_url", "") or ""),
    )


def build_safe_answer(
    retrieved: Sequence[RetrievedDevice] | None,
    reason: str,
    *,
    min_score: float = MIN_SCORE,
    max_devices: int = MAX_FALLBACK_DEVICES,
) -> Answer:
    if insufficient_evidence(retrieved, min_score=min_score):
        return abstain(reason, retrieved=retrieved)

    selected = _select_devices(retrieved, min_score, max_devices)
    citations: list[Citation] = []
    unverified: list[RetrievedDevice] = []

    for device in selected:
        if device.vigencia is None:
            unverified.append(device)
        else:
            citations.append(_citation_from_retrieved(device))

    if citations:
        response = (
            "Não consegui gerar uma resposta com segurança agora. "
            "Encontrei estes dispositivos recuperados na base, que podem ajudar a orientar você. "
            "Confira as citações abaixo e procure orientação jurídica individual."
        )
    else:
        response = (
            "Não consegui gerar uma resposta com segurança agora. "
            "Encontrei dispositivos recuperados na base, mas a vigência deles não pôde ser "
            "verificada. Confira o texto abaixo e procure orientação jurídica individual."
        )

    for device in unverified:
        response += (
            f"\n\nDispositivo {device.device_id} (vigência não verificada): {device.texto_literal}"
        )

    premissas = ["Nenhuma resposta foi gerada; exibindo apenas os dispositivos recuperados."]
    if unverified:
        premissas.append(
            "Vigência não verificada para: "
            + ", ".join(device.device_id for device in unverified)
            + "."
        )

    return Answer(
        resposta=response,
        citacoes=citations,
        proximos_passos=list(GUIDANCE_STEPS),
        encaminhamentos=[dict(item) for item in GUIDANCE_REFERRALS],
        premissas=premissas,
        nivel_confianca="baixo",
        abstencao=True,
        motivo_abstencao=reason,
    )
