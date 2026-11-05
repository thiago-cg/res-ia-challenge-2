import unicodedata

from pydantic import BaseModel

from src.contracts import Answer

EMERGENCY_BLOCK = """\
Se você está em perigo agora, ligue 190 (Polícia).
Se puder, vá para um local seguro e procure uma pessoa de confiança.
Não confronte o agressor.

A Central de Atendimento à Mulher é o 180 (24 horas).
Direitos Humanos: 100.
Polícia Civil: 197.

Você quer que eu te explique os direitos e os próximos passos depois?"""


class RiskAssessment(BaseModel):
    immediate: bool
    signals: list[str]
    kind: str | None = None


_CATEGORIES: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "agressao",
        (
            "esta me batendo",
            "esta me agredindo",
            "me agrediu agora",
            "me bateu agora",
            "esta aqui",
        ),
    ),
    (
        "ameaca_de_morte",
        (
            "vai me matar",
            "disse que me mata",
            "ameacou de me matar",
            "vou morrer",
        ),
    ),
    (
        "arma",
        (
            "esta com arma",
            "esta com faca",
            "esta armado",
            "portando arma",
            "com uma faca",
        ),
    ),
    (
        "carcere",
        (
            "estou presa",
            "estou trancada",
            "nao me deixa sair",
            "nao me deixou sair",
            "trancou a porta",
            "me trancou",
        ),
    ),
    (
        "perseguicao",
        (
            "esta me seguindo",
            "esta me perseguindo",
            "me perseguindo",
            "nao para de me perseguir",
        ),
    ),
    (
        "violencia_sexual",
        (
            "me forcou",
            "me estuprou",
            "estupro",
            "abusou sexualmente",
        ),
    ),
    (
        "crise",
        (
            "nao quero mais viver",
            "nao quero viver",
            "vou me matar",
            "quero morrer",
        ),
    ),
    (
        "crianca_em_risco",
        (
            "machucando meu filho",
            "agredindo meu filho",
            "meu filho esta sendo agredido",
            "batendo no meu filho",
        ),
    ),
)

_HISTORICAL_MARKERS = (
    "ha dois anos",
    "ha um ano",
    "ha anos",
    "ha meses",
    "meses atras",
    "no passado",
    "ano passado",
    "antigamente",
    "quando eramos casados",
    "ha muito tempo",
)


def _normalize(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text)
    without_accents = "".join(char for char in decomposed if not unicodedata.combining(char))
    return without_accents.lower()


def classify_risk(text: str) -> RiskAssessment:
    normalized = _normalize(text)

    signals: list[str] = []
    kind: str | None = None

    for category, patterns in _CATEGORIES:
        if any(pattern in normalized for pattern in patterns):
            signals.append(category)
            if kind is None:
                kind = category

    if signals:
        return RiskAssessment(immediate=True, signals=signals, kind=kind)

    if any(marker in normalized for marker in _HISTORICAL_MARKERS):
        return RiskAssessment(immediate=False, signals=["historical"], kind=None)

    return RiskAssessment(immediate=False, signals=[], kind=None)


def emergency_answer() -> Answer:
    return Answer(
        resposta=EMERGENCY_BLOCK,
        citacoes=[],
        proximos_passos=[
            "Ligar 190 (Polícia) se você estiver em perigo agora.",
            "Procurar um local seguro e uma pessoa de confiança.",
            "Ligar 180 (Central de Atendimento à Mulher).",
            "Procurar a DEAM mais próxima.",
            "Procurar a Defensoria Pública.",
        ],
        encaminhamentos=[
            {"tipo": "policia", "descricao": "Ligue 190 em caso de perigo imediato."},
            {
                "tipo": "central_mulher",
                "descricao": "A Central de Atendimento à Mulher atende pelo 180, 24 horas.",
            },
            {
                "tipo": "deam",
                "descricao": "Procure a Delegacia Especializada no Atendimento à Mulher.",
            },
            {
                "tipo": "defensoria",
                "descricao": "A Defensoria Pública pode orientar e acompanhar o caso.",
            },
        ],
        premissas=["Bloco de emergência exibido antes de qualquer busca."],
        nivel_confianca="alto",
        abstencao=False,
        motivo_abstencao=None,
    )
