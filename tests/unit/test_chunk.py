from __future__ import annotations

import pytest

from src.index.chunk import (
    ChunkTooLong,
    MissingVersionError,
    build_chunks,
    estimate_tokens,
)
from tests.fixtures.chunk_seed import (
    CITACAO_ALI_B,
    LMP_ART22_ALI_B,
    LMP_ART22_CAPUT,
    lmp_art22_context,
    lmp_art22_devices,
    lmp_art22_versions,
    make_device,
    make_version,
)


def test_lmp_art22_leaf_carries_identity_citation_and_context() -> None:
    chunks = build_chunks(lmp_art22_devices(), lmp_art22_versions())
    by_id = {chunk.device_id: chunk for chunk in chunks}

    alinea = by_id["lmp/art22/cpt/inc3/ali-b"]
    assert alinea.parent_id == "lmp/art22/cpt/inc3"
    assert alinea.artigo_id == "lmp/art22"
    assert alinea.norm_id == "lmp"
    assert alinea.tipo == "alinea"
    assert alinea.texto_literal == LMP_ART22_ALI_B
    assert alinea.citacao == CITACAO_ALI_B
    assert alinea.contexto == lmp_art22_context('caput, inciso III, alínea "b"')
    assert alinea.vigencia_status == "vigente"
    assert alinea.vigencia_inicio.isoformat() == "2006-09-22"
    assert alinea.vigencia_fim is None
    assert alinea.texto_indexacao == alinea.contexto + "\n" + alinea.texto_literal

    inciso = by_id["lmp/art22/cpt/inc3"]
    assert inciso.parent_id == "lmp/art22/cpt"
    assert inciso.artigo_id == "lmp/art22"
    assert inciso.texto_literal == "proibição de determinadas condutas, entre as quais:"


def test_article_context_is_produced_once_per_article() -> None:
    devices = lmp_art22_devices()
    versions = lmp_art22_versions()

    devices.append(
        make_device(
            "lmp/art22/cpt/inc4",
            parent_id="lmp/art22/cpt",
            tipo="inciso",
            rotulo="inciso IV",
            caminho="Título III > Capítulo II > Art. 22 > IV",
            ordem=5,
        )
    )
    versions.append(
        make_version(
            "lmp/art22/cpt/inc4",
            "medida de afastamento do lar;",
            contexto=lmp_art22_context("caput, inciso IV"),
        )
    )

    chunk_set = build_chunks(devices, versions)
    article_chunks = [chunk for chunk in chunk_set.chunks if chunk.device_id == "lmp/art22"]

    assert len(article_chunks) == 1
    assert article_chunks[0].artigo_id == "lmp/art22"
    assert (
        len([chunk for chunk in chunk_set.chunks if chunk.device_id.startswith("lmp/art22/cpt")])
        == 4
    )
    assert len(chunk_set.article_contexts) == 1
    assert set(chunk_set.article_contexts[0].leaf_device_ids) == {
        "lmp/art22/cpt",
        "lmp/art22/cpt/inc3",
        "lmp/art22/cpt/inc3/ali-b",
        "lmp/art22/cpt/inc4",
    }


def test_article_context_is_synthesized_when_article_node_is_missing() -> None:
    devices = [device for device in lmp_art22_devices() if device.id != "lmp/art22"]
    versions = [version for version in lmp_art22_versions() if version.device_id != "lmp/art22"]

    chunk_set = build_chunks(devices, versions)

    assert [chunk for chunk in chunk_set.chunks if chunk.device_id == "lmp/art22"] == []
    assert len(chunk_set.article_contexts) == 1
    context = chunk_set.article_contexts[0]
    assert context.artigo_id == "lmp/art22"
    assert context.texto_literal == LMP_ART22_CAPUT
    assert context.texto_indexacao == context.contexto + "\n" + context.texto_literal
    assert context.leaf_device_ids
    assert all(chunk.device_id in {device.id for device in devices} for chunk in chunk_set.chunks)


def test_long_parent_is_split_losslessly_into_structural_children() -> None:
    first = " ".join(["alfa"] * 50)
    second = " ".join(["beta"] * 50)
    long_literal = f"{first} {second}"
    devices = [
        make_device("lmp/art99", tipo="artigo", rotulo="Art. 99", artigo_id="lmp/art99"),
        make_device(
            "lmp/art99/cpt/inc1",
            parent_id="lmp/art99",
            artigo_id="lmp/art99",
            tipo="inciso",
            rotulo="inciso I",
            ordem=2,
        ),
        make_device(
            "lmp/art99/cpt/inc2",
            parent_id="lmp/art99",
            artigo_id="lmp/art99",
            tipo="inciso",
            rotulo="inciso II",
            ordem=3,
        ),
    ]
    versions = [
        make_version("lmp/art99", long_literal, contexto="Art. 99"),
        make_version("lmp/art99/cpt/inc1", first, contexto="Art. 99, I"),
        make_version("lmp/art99/cpt/inc2", second, contexto="Art. 99, II"),
    ]

    chunk_set = build_chunks(devices, versions, max_tokens=100)
    by_id = {chunk.device_id: chunk for chunk in chunk_set.chunks}

    assert "lmp/art99" not in by_id
    assert by_id["lmp/art99/cpt/inc1"].texto_literal == first
    assert by_id["lmp/art99/cpt/inc2"].texto_literal == second
    assert all(chunk.texto_literal for chunk in chunk_set.chunks)
    covered_words = " ".join(
        [by_id["lmp/art99/cpt/inc1"].texto_literal, by_id["lmp/art99/cpt/inc2"].texto_literal]
    ).split()
    assert covered_words == long_literal.split()
    assert len(chunk_set.article_contexts) == 1


def test_long_parent_with_uncovered_literal_raises_instead_of_losing_text() -> None:
    first = " ".join(["alfa"] * 50)
    second = " ".join(["beta"] * 50)
    long_literal = f"introducao ausente {first} {second}"
    devices = [
        make_device("lmp/art96", tipo="artigo", rotulo="Art. 96", artigo_id="lmp/art96"),
        make_device(
            "lmp/art96/cpt/inc1",
            parent_id="lmp/art96",
            artigo_id="lmp/art96",
            tipo="inciso",
            rotulo="inciso I",
            ordem=2,
        ),
        make_device(
            "lmp/art96/cpt/inc2",
            parent_id="lmp/art96",
            artigo_id="lmp/art96",
            tipo="inciso",
            rotulo="inciso II",
            ordem=3,
        ),
    ]
    versions = [
        make_version("lmp/art96", long_literal, contexto="Art. 96"),
        make_version("lmp/art96/cpt/inc1", first, contexto="Art. 96, I"),
        make_version("lmp/art96/cpt/inc2", second, contexto="Art. 96, II"),
    ]

    with pytest.raises(ChunkTooLong) as excinfo:
        build_chunks(devices, versions, max_tokens=100)

    assert excinfo.value.device_id == "lmp/art96"


def test_parent_split_requires_multiset_word_coverage() -> None:
    devices = [
        make_device("lmp/art94", tipo="artigo", artigo_id="lmp/art94"),
        make_device(
            "lmp/art94/cpt",
            parent_id="lmp/art94",
            artigo_id="lmp/art94",
            tipo="caput",
            ordem=2,
        ),
    ]
    versions = [
        make_version("lmp/art94", "a a", contexto="x x"),
        make_version("lmp/art94/cpt", "a", contexto=""),
    ]

    with pytest.raises(ChunkTooLong) as excinfo:
        build_chunks(devices, versions, max_tokens=4)

    assert excinfo.value.device_id == "lmp/art94"


def test_parent_split_allows_legitimate_extra_child_words() -> None:
    devices = [
        make_device("lmp/art93", tipo="artigo", artigo_id="lmp/art93"),
        make_device(
            "lmp/art93/cpt/inc1",
            parent_id="lmp/art93",
            artigo_id="lmp/art93",
            tipo="inciso",
            ordem=2,
        ),
        make_device(
            "lmp/art93/cpt/inc2",
            parent_id="lmp/art93",
            artigo_id="lmp/art93",
            tipo="inciso",
            ordem=3,
        ),
    ]
    versions = [
        make_version("lmp/art93", "a b", contexto="x x"),
        make_version("lmp/art93/cpt/inc1", "a x", contexto=""),
        make_version("lmp/art93/cpt/inc2", "b", contexto=""),
    ]

    chunk_set = build_chunks(devices, versions, max_tokens=4)
    literals = [chunk.texto_literal for chunk in chunk_set.chunks]

    assert "a b" not in literals
    assert set(literals) == {"a x", "b"}


def test_article_parent_fully_covered_by_caput_is_split_losslessly() -> None:
    devices = [
        make_device("lmp/art92", tipo="artigo", artigo_id="lmp/art92"),
        make_device(
            "lmp/art92/cpt",
            parent_id="lmp/art92",
            artigo_id="lmp/art92",
            tipo="caput",
            ordem=2,
        ),
    ]
    versions = [
        make_version("lmp/art92", "a b", contexto="x x"),
        make_version("lmp/art92/cpt", "a b", contexto=""),
    ]

    chunk_set = build_chunks(devices, versions, max_tokens=4)

    assert [chunk.device_id for chunk in chunk_set.chunks] == ["lmp/art92/cpt"]
    assert chunk_set.chunks[0].texto_literal == "a b"
    assert chunk_set.article_contexts[0].texto_literal == "a b"


def test_empty_literal_device_is_not_emitted_as_empty_chunk() -> None:
    devices = [
        make_device("lmp/art95", tipo="artigo", artigo_id="lmp/art95"),
        make_device(
            "lmp/art95/cpt",
            parent_id="lmp/art95",
            artigo_id="lmp/art95",
            tipo="caput",
            ordem=2,
        ),
    ]
    versions = [
        make_version("lmp/art95", "", contexto="Art. 95"),
        make_version("lmp/art95/cpt", "texto do caput", contexto="Art. 95, caput"),
    ]

    chunk_set = build_chunks(devices, versions)

    assert [chunk.device_id for chunk in chunk_set.chunks] == ["lmp/art95/cpt"]
    assert all(chunk.texto_literal for chunk in chunk_set.chunks)
    assert len(chunk_set.article_contexts) == 1
    assert chunk_set.article_contexts[0].texto_literal == "texto do caput"
    assert chunk_set.article_contexts[0].texto_literal.strip()


def test_long_leaf_without_children_raises_instead_of_truncating() -> None:
    long_literal = " ".join(["palavra"] * 2_000)
    devices = [make_device("lmp/art98", tipo="artigo", artigo_id="lmp/art98")]
    versions = [make_version("lmp/art98", long_literal, contexto="Art. 98")]

    with pytest.raises(ChunkTooLong) as excinfo:
        build_chunks(devices, versions, max_tokens=100)

    assert excinfo.value.device_id == "lmp/art98"
    assert "lmp/art98" in str(excinfo.value)


def test_missing_version_raises_clear_error() -> None:
    devices = lmp_art22_devices()
    versions = [
        version
        for version in lmp_art22_versions()
        if version.device_id != "lmp/art22/cpt/inc3/ali-b"
    ]

    with pytest.raises(MissingVersionError) as excinfo:
        build_chunks(devices, versions)

    assert excinfo.value.device_id == "lmp/art22/cpt/inc3/ali-b"
    assert "lmp/art22/cpt/inc3/ali-b" in str(excinfo.value)


def test_duplicate_versions_are_deduped_by_device_and_version() -> None:
    devices = lmp_art22_devices()
    versions = lmp_art22_versions() + lmp_art22_versions()

    chunks = build_chunks(devices, versions)
    keys = [(chunk.device_id, chunk.norm_version_id) for chunk in chunks]

    assert len(keys) == len(set(keys))


def test_default_token_estimator_scales_whitespace_by_1_3() -> None:
    text = " ".join(["palavra"] * 10)

    assert estimate_tokens(text) == 13
    assert estimate_tokens(text, tokenizer=lambda _: 7) == 7


def test_injected_tokenizer_can_relax_long_text_limit() -> None:
    long_literal = " ".join(["palavra"] * 2_000)
    devices = [make_device("lmp/art97", tipo="artigo", artigo_id="lmp/art97")]
    versions = [make_version("lmp/art97", long_literal, contexto="Art. 97")]

    chunks = build_chunks(devices, versions, max_tokens=100, tokenizer=lambda _: 1)

    assert [chunk.device_id for chunk in chunks] == ["lmp/art97"]
