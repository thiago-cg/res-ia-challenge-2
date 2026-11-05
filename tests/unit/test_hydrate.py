from __future__ import annotations

import pytest

from src.contracts import InvalidCitation, RetrievedDevice
from src.retrieve.hydrate import hydrate, resolve_citation


class FakeRepo:
    def __init__(self, rows: dict[tuple[str, int], dict] | None = None) -> None:
        self.rows = rows or {}
        self.calls: list[tuple[str, int]] = []

    def get_device_version(self, device_id: str, norm_version_id: int) -> dict | None:
        self.calls.append((device_id, norm_version_id))
        return self.rows.get((device_id, norm_version_id))


def row(
    texto: str,
    *,
    version: int = 1,
    citacao: str | None = None,
    vigencia: str = "vigente",
    contexto: str = "contexto",
    explicacao: str | None = None,
) -> dict:
    data = {
        "norm_version_id": version,
        "texto_literal": texto,
        "citacao": citacao or f"Lei nº 11.340/2006, art. 22 ({version})",
        "contexto": contexto,
        "vigencia_status": vigencia,
        "fonte_url": "https://www.planalto.gov.br",
    }
    if explicacao is not None:
        data["explicacao"] = explicacao
    return data


def retrieved(device_id: str, version: int = 1, score: float = 0.9) -> RetrievedDevice:
    return RetrievedDevice(
        device_id=device_id,
        norm_version_id=version,
        score=score,
        source="maxsim",
        texto_literal="",
        citacao="",
    )


def test_hydrate_two_norms_and_two_versions_without_cross_contamination() -> None:
    repo = FakeRepo(
        {
            ("lmp/art22", 1): row("texto lmp v1", version=1),
            ("lmp/art22", 2): row("texto lmp v2", version=2),
            ("cp/art129", 7): row("texto cp v7", version=7),
        }
    )

    result = hydrate(
        [("lmp/art22", 1), ("lmp/art22", 2), ("cp/art129", 7)],
        repo=repo,
    )

    assert [(item.device_id, item.norm_version_id) for item in result.devices] == [
        ("lmp/art22", 1),
        ("lmp/art22", 2),
        ("cp/art129", 7),
    ]
    assert [item.texto_literal for item in result.devices] == [
        "texto lmp v1",
        "texto lmp v2",
        "texto cp v7",
    ]
    assert result.incomplete_context == []


def test_hydrate_populates_vigencia_contexto_and_explicacao() -> None:
    repo = FakeRepo(
        {
            ("lmp/art22/cpt/inc3", 42): row(
                "contato com a ofendida",
                version=42,
                vigencia="alterado",
                contexto="Art. 22, caput",
                explicacao="Explicação simples.",
            )
        }
    )

    result = hydrate([("lmp/art22/cpt/inc3", 42)], repo=repo)

    device = result.devices[0]
    assert device.vigencia == "alterado"
    assert device.contexto == "Art. 22, caput"
    assert device.explicacao == "Explicação simples."
    assert device.fonte_url == "https://www.planalto.gov.br"


def test_hydrate_missing_pair_is_discarded_and_reported() -> None:
    repo = FakeRepo({("lmp/art22", 1): row("presente", version=1)})

    result = hydrate([("lmp/art22", 1), ("lmp/art22", 99)], repo=repo)

    assert [item.device_id for item in result.devices] == ["lmp/art22"]
    assert result.incomplete_context == [("lmp/art22", 99)]


def test_hydrate_rejects_row_from_another_version() -> None:
    repo = FakeRepo({("lmp/art22", 1): row("texto da versão 2", version=2)})

    result = hydrate([("lmp/art22", 1)], repo=repo)

    assert result.devices == []
    assert result.incomplete_context == [("lmp/art22", 1)]


def test_hydrate_preserves_candidate_score_and_source() -> None:
    repo = FakeRepo({("lmp/art22", 1): row("presente", version=1)})

    result = hydrate([retrieved("lmp/art22", 1, score=0.77)], repo=repo)

    assert result.devices[0].score == 0.77
    assert result.devices[0].source == "maxsim"


def test_resolve_citation_from_metadata() -> None:
    repo = FakeRepo({("lmp/art22", 42): row("texto", version=42)})

    citation = resolve_citation("lmp/art22", 42, repo=repo)

    assert citation.device_id == "lmp/art22"
    assert citation.norm_version_id == 42
    assert citation.texto == "texto"
    assert citation.vigencia == "vigente"
    assert citation.fonte_url == "https://www.planalto.gov.br"


def test_resolve_citation_missing_pair_raises_invalid_citation() -> None:
    with pytest.raises(InvalidCitation):
        resolve_citation("lmp/art22", 42, repo=FakeRepo())


def test_resolve_citation_version_mismatch_raises_invalid_citation() -> None:
    repo = FakeRepo({("lmp/art22", 42): row("texto", version=41)})

    with pytest.raises(InvalidCitation):
        resolve_citation("lmp/art22", 42, repo=repo)


def test_hydrate_invalid_vigencia_raises_invalid_citation() -> None:
    repo = FakeRepo({("lmp/art22", 1): row("texto", version=1, vigencia="banana")})

    with pytest.raises(InvalidCitation):
        hydrate([("lmp/art22", 1)], repo=repo)


def test_resolve_citation_invalid_vigencia_raises_invalid_citation() -> None:
    repo = FakeRepo({("lmp/art22", 42): row("texto", version=42, vigencia="banana")})

    with pytest.raises(InvalidCitation):
        resolve_citation("lmp/art22", 42, repo=repo)
