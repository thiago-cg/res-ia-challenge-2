import re
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


_IMMINENT: tuple[tuple[str, tuple[re.Pattern[str], ...]], ...] = tuple(
    (category, tuple(re.compile(pattern) for pattern in patterns))
    for category, patterns in (
        (
            "agressao",
            (
                r"esta (me )?(batendo|agredindo|empurrando|chutando|arrastando"
                r"|enforcando|espancando)",
                r"acabou de me (empurrar|bater|agredir|chutar|ameacar)",
                r"esta (quebrando|destruindo) (tudo|a casa|as coisas|os moveis)",
            ),
        ),
        (
            "ameaca_de_morte",
            (
                r"esta me ameacando",
                r"vai me matar",
                r"disse que me mata",
                r"vou morrer",
            ),
        ),
        (
            "arma",
            (
                r"esta com (um |uma |a |o )?(arma|faca|revolver|pistola|espingarda)",
                r"esta armado",
                r"portando arma",
            ),
        ),
        (
            "carcere",
            (
                r"estou (presa|trancada|escondida)",
                r"nao me (deixa|deixou) sair",
                r"trancou a porta",
                r"me trancou",
                r"batendo na porta",
            ),
        ),
        (
            "perseguicao",
            (
                r"esta me seguindo",
                r"esta me perseguindo",
                r"nao para de me perseguir",
            ),
        ),
        (
            "violencia_sexual",
            (
                r"esta me forcando",
                r"me forcando agora",
                r"esta me estuprando",
            ),
        ),
        (
            "crise",
            (
                r"nao quero mais viver",
                r"nao quero viver",
                r"vou me matar",
                r"quero morrer",
            ),
        ),
        (
            "crianca_em_risco",
            (
                r"(agredindo|batendo em|machucando) (meu|minha) (filho|filha|mae|pai|irmao|irma)",
                r"meu filho esta sendo agredido",
            ),
        ),
    )
)

#: Past forms.  Reporting a completed assault is still an emergency, so these
#: fire on their own -- unless the message is asking whether it is still in time
#: to report, which describes the same event as history.
_PAST: tuple[tuple[str, tuple[re.Pattern[str], ...]], ...] = tuple(
    (category, tuple(re.compile(pattern) for pattern in patterns))
    for category, patterns in (
        ("agressao", (r"(me|nos) (empurrou|agrediu|bateu|chutou|arrastou|enforcou)",)),
        ("ameaca_de_morte", (r"ameacou de me matar", r"(me|nos) ameacou")),
        ("violencia_sexual", (r"me forcou", r"me estuprou", r"abusou sexualmente")),
    )
)

#: Iterative forms ("ele fica me ameaçando") describe a pattern of behaviour,
#: not an event in progress, so they need a present marker to count.
_HABITUAL: tuple[tuple[str, tuple[re.Pattern[str], ...]], ...] = tuple(
    (category, tuple(re.compile(pattern) for pattern in patterns))
    for category, patterns in (
        ("ameaca_de_morte", (r"fica me ameacando", r"ameacando (me|minha|meu)")),
        ("perseguicao", (r"me perseguindo", r"me seguindo")),
    )
)

_HISTORICAL_RE = re.compile(
    r"\bha\s+"
    r"(?:(?:\d+|um|uma|dois|duas|tres|quatro|cinco|seis|dez|muitos|muitas|alguns|algumas)\s+)?"
    r"(?:ano|anos|mes|meses|dia|dias|semana|semanas)\b"
    r"|\banos\s+atras\b"
    r"|\bmeses\s+atras\b"
    r"|\bdias\s+atras\b"
    r"|\bsemanas\s+atras\b"
    r"|\bontem\b"
    r"|\bno\s+passado\b"
    r"|\bano\s+passado\b"
    r"|\bantigamente\b"
    r"|\bquando\s+eu\s+era\b"
    r"|\bha\s+muito\s+tempo\b"
    r"|\bna\s+epoca\b"
)

_ONLY_NOW_RE = re.compile(r"\bso\s+agora\b")

_DEADLINE_RE = re.compile(
    r"\b(da|dar)\s+tempo\b"
    r"|\bainda\s+(posso|da|consigo|vale)\b"
    r"|\bprazo\b"
    r"|\bquando\s+(posso|devo)\s+denunciar\b"
    r"|\bnao\s+registrei\b"
    r"|\b(isso|isto)\s+e\s+crime\b"
)

_PRESENT_MARKERS = (
    "agora",
    "neste momento",
    "neste instante",
    "esta me",
    "estou presa",
    "estou trancada",
    "esta aqui",
    "nao me deixa sair",
    "nao para de",
    "hoje",
)


def _normalize(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text)
    without_accents = "".join(char for char in decomposed if not unicodedata.combining(char))
    return without_accents.lower()


def classify_risk(text: str) -> RiskAssessment:
    normalized = _normalize(text)

    historical = bool(_HISTORICAL_RE.search(normalized))
    only_now = bool(_ONLY_NOW_RE.search(normalized))
    present = any(marker in normalized for marker in _PRESENT_MARKERS) and not only_now
    deferred = bool(_DEADLINE_RE.search(normalized))

    signals: list[str] = []
    kind: str | None = None

    for tier, name in ((_IMMINENT, "imminent"), (_HABITUAL, "habitual"), (_PAST, "past")):
        if name == "habitual" and not present:
            continue
        if name == "past" and (deferred or only_now):
            continue
        for category, patterns in tier:
            if any(pattern.search(normalized) for pattern in patterns):
                signals.append(category)
                if kind is None:
                    kind = category
        if signals:
            break

    if signals:
        if historical and not present:
            return RiskAssessment(immediate=False, signals=["historical"], kind=None)
        return RiskAssessment(immediate=True, signals=signals, kind=kind)

    if historical:
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
