"""Guards for the real ``data/sources.yaml`` manifest (not a fixture)."""

from __future__ import annotations

from pathlib import Path
from urllib.parse import urlparse

import pytest

from src.ingest.fetch import Source, load_sources
from src.ingest.models import SOURCE_NORMS, build_norm, norm_display

MANIFEST = Path(__file__).resolve().parents[2] / "data" / "sources.yaml"
OFFICIAL_HOSTS = {
    "www.planalto.gov.br",
    "atos.cnj.jus.br",
    "scon.stj.jus.br",
}
# Texto compilado já incorpora estas leis alteradoras; ficam desligadas até o
# benchmark mostrar que ajudam (docs/03-dados-e-fontes.md, seção 2.1).
REDUNDANT_AMENDING_LAWS = {
    "lei-13827-2019",
    "lei-13505-2017",
    "lei-13894-2019",
    "lei-14310-2022",
    "lei-14674-2023",
    "lei-14857-2024",
}


@pytest.fixture(scope="module")
def sources() -> list[Source]:
    return load_sources(MANIFEST)


def test_manifest_urls_are_official_https(sources: list[Source]) -> None:
    for source in sources:
        parsed = urlparse(source.url)
        assert parsed.scheme == "https", source.id
        assert parsed.hostname in OFFICIAL_HOSTS, f"{source.id}: {parsed.hostname}"


def test_enabled_sources_have_norm_metadata(sources: list[Source]) -> None:
    # stj-sumulas e os demais P0 antigos têm entrada própria; toda fonte habilitada
    # precisa de metadados explícitos para que a vigência não caia no padrão 1970.
    missing = [s.id for s in sources if s.enabled and s.id not in SOURCE_NORMS]
    assert missing == []


def test_norm_metadata_points_to_the_manifest_url(sources: list[Source]) -> None:
    for source in sources:
        meta = SOURCE_NORMS.get(source.id)
        if meta is None or not source.enabled:
            continue
        if source.id in {"stj-sumulas"}:
            continue  # a URL da norma é a página de busca; a do manifesto é o PDF
        assert meta.fonte_url.lower() == source.url.lower(), source.id


def test_redundant_amending_laws_stay_disabled_until_benchmarked(
    sources: list[Source],
) -> None:
    by_id = {source.id: source for source in sources}
    for source_id in REDUNDANT_AMENDING_LAWS:
        assert source_id in by_id, source_id
        assert by_id[source_id].enabled is False, source_id


def test_recent_amending_laws_are_enabled_with_exact_dates(sources: list[Source]) -> None:
    by_id = {source.id: source for source in sources}
    for source_id in ("lei-15412-2026", "lei-15380-2026", "lei-15125-2025"):
        assert by_id[source_id].enabled is True, source_id
        assert by_id[source_id].priority == "P0", source_id
        assert SOURCE_NORMS[source_id].data_exata is True, source_id


def test_new_norms_render_a_readable_citation_label() -> None:
    assert norm_display(build_norm("cnj-res-254-2018")) == "Resolução CNJ nº 254/2018"
    assert norm_display(build_norm("decreto-7958-2013")) == "Decreto nº 7.958/2013"
    assert norm_display(build_norm("lei-14149-2021")) == (
        "Lei nº 14.149/2021 (Formulário Nacional de Avaliação de Risco)"
    )
