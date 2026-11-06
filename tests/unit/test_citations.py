from dataclasses import dataclass

import pytest

from src.retrieve.citations import ParsedCitation, parse_citation, resolve_explicit_citation


@dataclass
class CatalogHit:
    device_id: str
    norm_id: str
    artigo_id: str


class FakeCatalog:
    def __init__(self, entries: dict[tuple[str, str], CatalogHit] | None = None) -> None:
        self.entries = entries or {}
        self.calls: list[tuple[str, str]] = []

    def find(self, norm_id: str, artigo_id: str) -> CatalogHit | None:
        self.calls.append((norm_id, artigo_id))
        return self.entries.get((norm_id, artigo_id))


LMP_CATALOG = FakeCatalog(
    {
        ("lmp", "lmp/art7"): CatalogHit("lmp/art7", "lmp", "lmp/art7"),
        ("lmp", "lmp/art24-a"): CatalogHit("lmp/art24-a", "lmp", "lmp/art24-a"),
        ("lmp", "lmp/art22"): CatalogHit("lmp/art22", "lmp", "lmp/art22"),
        ("lmp", "lmp/art22/cpt/inc3"): CatalogHit("lmp/art22/cpt/inc3", "lmp", "lmp/art22"),
        ("lmp", "lmp/art22/cpt/inc3/ali-b"): CatalogHit(
            "lmp/art22/cpt/inc3/ali-b", "lmp", "lmp/art22"
        ),
        ("lmp", "lmp/art22/par1/inc3"): CatalogHit("lmp/art22/par1/inc3", "lmp", "lmp/art22"),
        ("lmp", "lmp/art22/par-unico"): CatalogHit("lmp/art22/par-unico", "lmp", "lmp/art22"),
    }
)


def test_parse_article() -> None:
    parsed = parse_citation("art. 7º")
    assert parsed.artigo == 7
    assert parsed.artigo_sufixo is None
    assert parsed.norm_hint is None
    assert parsed.raw == "art. 7º"


def test_parse_article_with_letter_suffix() -> None:
    parsed = parse_citation("art. 24-A da Lei Maria da Penha")
    assert parsed.artigo == 24
    assert parsed.artigo_sufixo == "a"
    assert parsed.norm_hint == "lmp"


def test_parse_inciso_and_alinea() -> None:
    inciso = parse_citation("inciso III")
    assert inciso.inciso == 3
    assert inciso.artigo is None

    alinea = parse_citation("alínea b")
    assert alinea.alinea == "b"

    item = parse_citation("item 2")
    assert item.item == 2


def test_parse_full_citation() -> None:
    parsed = parse_citation("art. 5º, § 1º, inciso II, alínea b")
    assert parsed.artigo == 5
    assert parsed.paragrafo == 1
    assert parsed.inciso == 2
    assert parsed.alinea == "b"


def test_parse_bare_inciso_and_quoted_alinea() -> None:
    parsed = parse_citation('art. 22, III, "b"')
    assert parsed.artigo == 22
    assert parsed.inciso == 3
    assert parsed.alinea == "b"


def test_parse_article_in_prose_does_not_capture_a_prose_letter() -> None:
    parsed = parse_citation("O que diz o art. 7º da Lei Maria da Penha?")

    assert parsed.artigo == 7
    assert parsed.alinea is None


def test_parse_paragrafo_unico() -> None:
    parsed = parse_citation("art. 22, parágrafo único, inciso III")

    assert parsed.artigo == 22
    assert parsed.paragrafo is None
    assert parsed.paragrafo_unico is True
    assert parsed.inciso == 3


def test_parse_returns_empty_citation() -> None:
    parsed = parse_citation("como faço para denunciar?")
    assert parsed == ParsedCitation(
        norm_hint=None,
        artigo=None,
        artigo_sufixo=None,
        paragrafo=None,
        inciso=None,
        alinea=None,
        item=None,
        raw="como faço para denunciar?",
    )


def test_resolve_inexistent_article_abstains() -> None:
    result = resolve_explicit_citation("art. 999 da Lei Maria da Penha", catalog=LMP_CATALOG)
    assert result.resolved is False
    assert result.reason == "not_found"
    assert result.device_id is None
    assert result.ambiguous is False


def test_resolve_explicit_citation_with_catalog() -> None:
    result = resolve_explicit_citation("art. 7º da Lei Maria da Penha", catalog=LMP_CATALOG)
    assert result.resolved is True
    assert result.device_id == "lmp/art7"
    assert result.norm_id == "lmp"
    assert result.artigo_id == "lmp/art7"
    assert result.reason is None


def test_resolve_hyphenated_article() -> None:
    result = resolve_explicit_citation("art. 24-A da Lei Maria da Penha", catalog=LMP_CATALOG)
    assert result.resolved is True
    assert result.device_id == "lmp/art24-a"
    assert LMP_CATALOG.calls[-1] == ("lmp", "lmp/art24-a")


def test_resolve_leaf_citation_uses_the_full_canonical_device_id() -> None:
    result = resolve_explicit_citation(
        'art. 22, III, "b" da Lei Maria da Penha', catalog=LMP_CATALOG
    )

    assert result.resolved is True
    assert result.device_id == "lmp/art22/cpt/inc3/ali-b"
    assert result.artigo_id == "lmp/art22"
    assert LMP_CATALOG.calls[-1] == ("lmp", "lmp/art22/cpt/inc3/ali-b")


def test_resolve_paragraph_leaf_without_caput_segment() -> None:
    result = resolve_explicit_citation(
        "art. 22, § 1º, inciso III da Lei Maria da Penha", catalog=LMP_CATALOG
    )

    assert result.resolved is True
    assert result.device_id == "lmp/art22/par1/inc3"
    assert LMP_CATALOG.calls[-1] == ("lmp", "lmp/art22/par1/inc3")


def test_nonexistent_inciso_under_existing_article_abstains() -> None:
    result = resolve_explicit_citation(
        "art. 22, inciso IX da Lei Maria da Penha", catalog=LMP_CATALOG
    )

    assert result.resolved is False
    assert result.reason == "not_found"
    assert result.device_id is None
    assert LMP_CATALOG.calls[-1] == ("lmp", "lmp/art22/cpt/inc9")


def test_leading_inciso_attaches_to_the_following_article() -> None:
    result = resolve_explicit_citation(
        "inciso III do art. 22 da Lei Maria da Penha", catalog=LMP_CATALOG
    )

    assert result.resolved is True
    assert result.device_id == "lmp/art22/cpt/inc3"
    assert LMP_CATALOG.calls[-1] == ("lmp", "lmp/art22/cpt/inc3")


def test_missing_leading_inciso_abstains_without_parent_fallback() -> None:
    result = resolve_explicit_citation(
        "inciso IX do art. 22 da Lei Maria da Penha", catalog=LMP_CATALOG
    )

    assert result.resolved is False
    assert result.reason == "not_found"
    assert result.device_id is None
    assert LMP_CATALOG.calls[-1] == ("lmp", "lmp/art22/cpt/inc9")


def test_leading_paragrafo_unico_attaches_to_the_article() -> None:
    result = resolve_explicit_citation(
        "parágrafo único do art. 22 da Lei Maria da Penha", catalog=LMP_CATALOG
    )

    assert result.resolved is True
    assert result.device_id == "lmp/art22/par-unico"
    assert LMP_CATALOG.calls[-1] == ("lmp", "lmp/art22/par-unico")


def test_leading_full_chain_attaches_in_canonical_order() -> None:
    result = resolve_explicit_citation(
        "alínea b do inciso III do art. 22 da Lei Maria da Penha", catalog=LMP_CATALOG
    )

    assert result.resolved is True
    assert result.device_id == "lmp/art22/cpt/inc3/ali-b"
    assert LMP_CATALOG.calls[-1] == ("lmp", "lmp/art22/cpt/inc3/ali-b")


def test_leading_qualifiers_parse_even_after_prose() -> None:
    parsed = parse_citation("O que diz o inciso III do art. 22 da Lei Maria da Penha?")

    assert parsed.artigo == 22
    assert parsed.inciso == 3
    assert parsed.alinea is None


def test_resolve_uses_norm_hint_argument() -> None:
    result = resolve_explicit_citation("art. 22", catalog=LMP_CATALOG, norm_hint="lmp")
    assert result.resolved is True
    assert result.device_id == "lmp/art22"


def test_ambiguous_norm_is_flagged() -> None:
    calls_before = len(LMP_CATALOG.calls)
    result = resolve_explicit_citation("art. 22", catalog=LMP_CATALOG)
    assert result.resolved is False
    assert result.ambiguous is True
    assert result.reason == "norm_ambiguous"
    assert len(LMP_CATALOG.calls) == calls_before


def test_no_catalog_does_not_fake_a_hit() -> None:
    result = resolve_explicit_citation("art. 7º", norm_hint="lmp")
    assert result.resolved is False
    assert result.reason == "no_catalog"
    assert result.device_id is None


def test_no_citation_found() -> None:
    result = resolve_explicit_citation("quero ajuda", norm_hint="lmp", catalog=LMP_CATALOG)
    assert result.resolved is False
    assert result.reason == "no_citation"
    assert result.ambiguous is False


def test_catalog_receives_date_without_breaking_protocol() -> None:
    from datetime import date

    result = resolve_explicit_citation(
        "art. 7º da Lei Maria da Penha",
        catalog=LMP_CATALOG,
        data_fato=date(2020, 1, 1),
    )
    assert result.resolved is True


def test_dict_catalog_result_is_supported() -> None:
    class DictCatalog:
        def find(self, norm_id: str, artigo_id: str) -> dict[str, str] | None:
            if (norm_id, artigo_id) == ("lmp", "lmp/art7"):
                return {"device_id": "lmp/art7", "norm_id": "lmp", "artigo_id": "lmp/art7"}
            return None

    result = resolve_explicit_citation("art. 7º da LMP", catalog=DictCatalog())
    assert result.resolved is True
    assert result.device_id == "lmp/art7"


@pytest.mark.parametrize(
    ("text", "expected_norm"),
    [
        ("art. 7º da Lei Maria da Penha", "lmp"),
        ("art. 7º da Lei 11.340/2006", "lmp"),
        ("art. 129 do Código Penal", "cp"),
        ("art. 38 do CPP", "cpp"),
        ("art. 5º da Constituição Federal", "cf"),
    ],
)
def test_norm_hint_detection(text: str, expected_norm: str) -> None:
    assert parse_citation(text).norm_hint == expected_norm
