"""Hand-built LMP art. 22 fixtures for chunker and embedding tests.

The fixtures model the Planalto hierarchy used throughout docs/04: an article
identity node, a caput, inciso III and alínea "b".  Versions carry the
deterministic context/citation that ingestion is expected to produce, so tests
can exercise the identity/text join without importing ``src.ingest``.
"""

from __future__ import annotations

import hashlib
import unicodedata
from datetime import date
from uuid import NAMESPACE_URL, UUID, uuid5

from src.contracts import Device, DeviceVersion

LMP_NORM_ID = "lmp"
LMP_VERSION_ID = 42
LMP_VIGENCIA_INICIO = date(2006, 9, 22)

LMP_ART22_CAPUT = (
    "Constatada a prática de violência doméstica e familiar contra a mulher, "
    "o juiz poderá aplicar, de imediato, ao agressor, em conjunto ou "
    "separadamente, as seguintes medidas protetivas de urgência, entre outras:"
)
LMP_ART22_INC3 = "proibição de determinadas condutas, entre as quais:"
LMP_ART22_ALI_B = (
    "contato com a ofendida, seus familiares e testemunhas por qualquer meio de comunicação;"
)

LMP_HEADER = (
    "Lei nº 11.340/2006 (Lei Maria da Penha)\n"
    "Título III — Das Medidas Protetivas de Urgência\n"
    "Capítulo II — Das Medidas Protetivas de Urgência que Obrigam o Agressor"
)

CITACAO_ART22 = "Lei nº 11.340/2006 (Lei Maria da Penha), art. 22, caput"
CITACAO_INC3 = "Lei nº 11.340/2006 (Lei Maria da Penha), art. 22, caput, inciso III"
CITACAO_ALI_B = 'Lei nº 11.340/2006 (Lei Maria da Penha), art. 22, caput, inciso III, alínea "b"'


def point_id(device_id: str, norm_version_id: int = LMP_VERSION_ID) -> UUID:
    return uuid5(NAMESPACE_URL, f"{device_id}@{norm_version_id}")


def content_hash(texto_literal: str) -> str:
    return hashlib.sha256(texto_literal.encode("utf-8")).hexdigest()


def normalize(text: str) -> str:
    stripped = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in stripped if not unicodedata.combining(ch)).lower()


def make_device(
    device_id: str,
    *,
    parent_id: str | None = None,
    artigo_id: str = "lmp/art22",
    tipo: str = "artigo",
    rotulo: str | None = None,
    caminho: str = "Título III > Capítulo II > Art. 22",
    ordem: int = 1,
    norm_id: str = LMP_NORM_ID,
) -> Device:
    return Device(
        id=device_id,
        norm_id=norm_id,
        parent_id=parent_id,
        artigo_id=artigo_id,
        tipo=tipo,  # type: ignore[arg-type]
        rotulo=rotulo or device_id,
        caminho=caminho,
        ordem=ordem,
    )


def make_version(
    device_id: str,
    texto_literal: str,
    *,
    contexto: str | None = None,
    citacao: str | None = None,
    norm_version_id: int = LMP_VERSION_ID,
    vigencia_status: str = "vigente",
    vigencia_inicio: date = LMP_VIGENCIA_INICIO,
    vigencia_fim: date | None = None,
) -> DeviceVersion:
    context = contexto if contexto is not None else LMP_HEADER
    citation = citacao if citacao is not None else CITACAO_ART22
    search_text = normalize(f"{context}\n{texto_literal}\n{citation}")
    return DeviceVersion(
        device_id=device_id,
        norm_version_id=norm_version_id,
        texto_literal=texto_literal,
        texto_anterior=None,
        contexto=context,
        citacao=citation,
        vigencia_status=vigencia_status,  # type: ignore[arg-type]
        redacao_dada_por=None,
        vigencia_inicio=vigencia_inicio,
        vigencia_fim=vigencia_fim,
        fonte_url="https://www.planalto.gov.br/ccivil_03/_ato2004-2006/2006/lei/l11340.htm",
        content_hash=content_hash(texto_literal),
        qdrant_point_id=point_id(device_id, norm_version_id),
        search_text=search_text,
    )


def lmp_art22_context(rotulo: str) -> str:
    return f"{LMP_HEADER}\nArt. 22, {rotulo}\n\n{LMP_ART22_CAPUT}"


def lmp_art22_devices() -> list[Device]:
    return [
        make_device(
            "lmp/art22",
            tipo="artigo",
            rotulo="Art. 22",
            caminho="Título III > Capítulo II > Art. 22",
            ordem=1,
        ),
        make_device(
            "lmp/art22/cpt",
            parent_id="lmp/art22",
            tipo="caput",
            rotulo="Art. 22, caput",
            caminho="Título III > Capítulo II > Art. 22 > caput",
            ordem=2,
        ),
        make_device(
            "lmp/art22/cpt/inc3",
            parent_id="lmp/art22/cpt",
            tipo="inciso",
            rotulo="inciso III",
            caminho="Título III > Capítulo II > Art. 22 > III",
            ordem=3,
        ),
        make_device(
            "lmp/art22/cpt/inc3/ali-b",
            parent_id="lmp/art22/cpt/inc3",
            tipo="alinea",
            rotulo='alínea "b"',
            caminho="Título III > Capítulo II > Art. 22 > III > b",
            ordem=4,
        ),
    ]


def lmp_art22_versions() -> list[DeviceVersion]:
    return [
        make_version(
            "lmp/art22",
            LMP_ART22_CAPUT,
            contexto=lmp_art22_context("caput"),
            citacao=CITACAO_ART22,
        ),
        make_version(
            "lmp/art22/cpt",
            LMP_ART22_CAPUT,
            contexto=lmp_art22_context("caput"),
            citacao=CITACAO_ART22,
        ),
        make_version(
            "lmp/art22/cpt/inc3",
            LMP_ART22_INC3,
            contexto=lmp_art22_context("caput, inciso III"),
            citacao=CITACAO_INC3,
        ),
        make_version(
            "lmp/art22/cpt/inc3/ali-b",
            LMP_ART22_ALI_B,
            contexto=lmp_art22_context('caput, inciso III, alínea "b"'),
            citacao=CITACAO_ALI_B,
        ),
    ]
