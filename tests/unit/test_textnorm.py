import pytest

from src.textnorm import normalize_citation_forms, normalize_search_text, strip_accents


def test_strip_accents() -> None:
    assert strip_accents("Ação, violência, parágrafo") == "Acao, violencia, paragrafo"
    assert strip_accents("já está") == "ja esta"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("art. 7º", "artigo 7"),
        ("artigo 7", "artigo 7"),
        ("art 7°", "artigo 7"),
        ("§ 1º", "paragrafo 1"),
        ("§1º", "paragrafo 1"),
        ("parágrafo primeiro", "paragrafo 1"),
        ("inc. II", "inciso 2"),
        ("inciso II", "inciso 2"),
        ("al. b", "alinea b"),
        ("alínea b", "alinea b"),
        ("24-A", "24-a"),
        ("BO", "boletim de ocorrencia"),
        ("medida protetiva", "medida protetiva"),
        ("medida de proteção", "medida protetiva"),
    ],
)
def test_normalization_table(raw: str, expected: str) -> None:
    assert normalize_search_text(raw) == expected
    assert normalize_citation_forms(raw) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("arts. 5º e 6º", "artigo 5 artigo 6"),
        ("§§ 1º a 3º", "paragrafo 1 paragrafo 2 paragrafo 3"),
        ("incisos I e II", "inciso 1 inciso 2"),
        ("alíneas a e b", "alinea a alinea b"),
        ("art. 7º, inciso II", "artigo 7 inciso 2"),
        ("art. 24-A", "artigo 24-a"),
        ("art. 5º, § 1º", "artigo 5 paragrafo 1"),
    ],
)
def test_citation_grammar_table(raw: str, expected: str) -> None:
    assert normalize_search_text(raw) == expected
    assert normalize_citation_forms(raw) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("art. 5º a 7º", "artigo 5 artigo 6 artigo 7"),
        ("artigos 5-6", "artigo 5 artigo 6"),
        ("§ 2º até 4º", "paragrafo 2 paragrafo 3 paragrafo 4"),
        ("inciso I até III", "inciso 1 inciso 2 inciso 3"),
        ("inciso II e IV", "inciso 2 inciso 4"),
        ("alínea a até c", "alinea a alinea b alinea c"),
        ("art. 24-A", "artigo 24-a"),
        ("artigo 24-a", "artigo 24-a"),
        ("parágrafo único", "paragrafo unico"),
        ("ART. 7º", "artigo 7"),
        ("  art.   7º  ", "artigo 7"),
    ],
)
def test_range_expansion_and_edge_cases(raw: str, expected: str) -> None:
    assert normalize_search_text(raw) == expected


def test_24a_is_not_a_range() -> None:
    normalized = normalize_search_text("art. 24-A")
    assert "artigo 24 artigo" not in normalized
    assert normalized == "artigo 24-a"


def test_normalization_is_idempotent() -> None:
    once = normalize_search_text("arts. 5º e 6º, § 1º, inciso II")
    assert normalize_search_text(once) == once
