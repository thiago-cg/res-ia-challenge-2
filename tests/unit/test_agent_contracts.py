"""T05 — fronteiras dos contratos entre os agentes.

Estes testes existem antes de src/agents/contracts.py existir: o primeiro run falha por
ModuleNotFoundError. Eles cobrem a matriz de §7.5 do briefing (campos desconhecidos, enums
inválidos, limite de tamanho, JSON malformado, política adulterada, dados não serializáveis).
"""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError


def _pedido(**over: object) -> dict:
    base = {
        "request_id": "r-1",
        "turn_id": "t-1",
        "pergunta_autossuficiente": "Qual o prazo para representar?",
    }
    base.update(over)
    return base


# --------------------------------------------------------------------------- PedidoPesquisa
def test_pedido_minimo_e_valido() -> None:
    from src.agents.contracts import PedidoPesquisa

    pedido = PedidoPesquisa(**_pedido())
    assert pedido.schema_version == "pesquisa.v1"
    assert pedido.contexto_minimo == ""
    assert pedido.pontos_a_verificar == []


def test_pedido_rejeita_campo_desconhecido() -> None:
    from src.agents.contracts import PedidoPesquisa

    with pytest.raises(ValidationError):
        PedidoPesquisa(**_pedido(), permitir_web=True)  # política não vem do modelo


def test_pedido_rejeita_versao_de_schema_desconhecida() -> None:
    from src.agents.contracts import PedidoPesquisa

    with pytest.raises(ValidationError):
        PedidoPesquisa(**_pedido(schema_version="pesquisa.v2"))


def test_pedido_rejeita_pergunta_vazia_e_gigante() -> None:
    from src.agents.contracts import PedidoPesquisa

    with pytest.raises(ValidationError):
        PedidoPesquisa(**_pedido(pergunta_autossuficiente=""))
    with pytest.raises(ValidationError):
        PedidoPesquisa(**_pedido(pergunta_autossuficiente="x" * 2001))


def test_pedido_rejeita_json_malformado() -> None:
    from src.agents.contracts import PedidoPesquisa

    with pytest.raises(ValidationError):
        PedidoPesquisa.model_validate_json("{nao e json}")


def test_pedido_com_dado_nao_serializavel_nao_exporta() -> None:
    from src.agents.contracts import PedidoPesquisa

    pedido = PedidoPesquisa(**_pedido())
    assert json.loads(pedido.model_dump_json())["request_id"] == "r-1"


# --------------------------------------------------------------------------- Política
def test_politica_e_injetada_e_imutavel() -> None:
    from src.agents.contracts import PoliticaPesquisa

    politica = PoliticaPesquisa(max_buscas=3)
    assert politica.permitir_web is False  # padrão seguro
    with pytest.raises(ValidationError):
        politica.max_buscas = 99  # frozen


def test_politica_rejeita_campo_extra() -> None:
    from src.agents.contracts import PoliticaPesquisa

    with pytest.raises(ValidationError):
        PoliticaPesquisa(max_buscas=3, contornar_limites=True)


# --------------------------------------------------------------------------- ResultadoPesquisa
def test_resultado_aceita_uniao_discriminada() -> None:
    from src.agents.contracts import ResultadoPesquisa

    resultado = ResultadoPesquisa(
        request_id="r-1",
        status="parcial",
        evidencias=[
            {
                "kind": "base",
                "evidence_id": "e1",
                "device_id": "lmp/art22",
                "norm_version_id": 7,
            },
            {
                "kind": "web",
                "evidence_id": "e2",
                "url_validada": "https://www.planalto.gov.br/x",
                "publicador": "Planalto",
                "data_acesso": "2026-11-16",
                "trecho": "trecho",
                "snapshot_hash": "sha256:abc",
            },
        ],
    )
    assert [e.kind for e in resultado.evidencias] == ["base", "web"]


def test_resultado_rejeita_discriminador_invalido() -> None:
    from src.agents.contracts import ResultadoPesquisa

    with pytest.raises(ValidationError):
        ResultadoPesquisa(
            request_id="r-1",
            status="suficiente",
            evidencias=[{"kind": "memoria", "evidence_id": "e1"}],
        )


def test_evidencia_web_nao_se_disfarca_de_base() -> None:
    """INV08: evidência web não pode ser aceita como dispositivo da base."""
    from src.agents.contracts import EvidenciaBase

    with pytest.raises(ValidationError):
        EvidenciaBase(
            evidence_id="e1",
            device_id="lmp/art22",
            norm_version_id=7,
            url_validada="https://example.test",
        )


def test_resultado_rejeita_status_fora_do_enum() -> None:
    from src.agents.contracts import ResultadoPesquisa

    with pytest.raises(ValidationError):
        ResultadoPesquisa(request_id="r-1", status="talvez")


def test_resultado_limita_quantidade_de_evidencias() -> None:
    from src.agents.contracts import ResultadoPesquisa

    item = {"kind": "base", "evidence_id": "e", "device_id": "d", "norm_version_id": 1}
    with pytest.raises(ValidationError):
        ResultadoPesquisa(request_id="r-1", status="suficiente", evidencias=[item] * 21)


# --------------------------------------------------------------------------- OutputKind
def test_output_kind_tem_os_cinco_tipos_e_recusa_desconhecido() -> None:
    from src.agents.contracts import RespostaConversa

    ok = RespostaConversa(kind="social", texto="resposta")
    assert ok.kind == "social"
    with pytest.raises(ValidationError):
        RespostaConversa(kind="opiniao", texto="x")


def test_resposta_social_nao_pode_citar_dispositivo() -> None:
    """A política de §21.6 é verificável no contrato, não só na prosa."""
    from src.agents.contracts import RespostaConversa

    with pytest.raises(ValidationError):
        RespostaConversa(kind="social", texto="oi", device_ids=["lmp/art22"])


def test_resposta_juridica_sem_citacao_e_recusada() -> None:
    from src.agents.contracts import RespostaConversa

    with pytest.raises(ValidationError):
        RespostaConversa(kind="juridica", texto="a lei diz...")


# =============================================================================================
# Achados da revisão independente do T05 (2026-11-16): cobertura que faltava e furos fechados.
# =============================================================================================
def test_dado_nao_serializavel_e_rejeitado() -> None:
    from src.agents.contracts import PedidoPesquisa

    with pytest.raises(ValidationError):
        PedidoPesquisa(**_pedido(request_id=object()))


def test_erro_de_validacao_nao_ecoa_o_relato() -> None:
    from src.agents.contracts import PedidoPesquisa

    segredo = "RELATO SECRETO DA VITIMA " * 200
    with pytest.raises(ValidationError) as exc:
        PedidoPesquisa(**_pedido(pergunta_autossuficiente=segredo))
    assert "RELATO SECRETO" not in str(exc.value)


def test_parent_request_id_vazio_e_rejeitado() -> None:
    from src.agents.contracts import PedidoPesquisa

    with pytest.raises(ValidationError):
        PedidoPesquisa(**_pedido(parent_request_id=""))


def test_itens_gigantes_sao_rejeitados() -> None:
    from src.agents.contracts import PedidoPesquisa, RespostaConversa, ResultadoPesquisa

    with pytest.raises(ValidationError):
        PedidoPesquisa(**_pedido(pontos_a_verificar=["x" * 500_000]))
    with pytest.raises(ValidationError):
        ResultadoPesquisa(request_id="r-1", status="suficiente", lacunas=["x" * 500_000])
    with pytest.raises(ValidationError):
        RespostaConversa(kind="juridica", texto="t", device_ids=["d" * 200_000])


@pytest.mark.parametrize(
    "classe,campo",
    [
        ("ResultadoPesquisa", "resultado"),
        ("EvidenciaWeb", "web"),
        ("RespostaConversa", "resposta"),
    ],
)
def test_extra_forbid_tambem_vale_para_os_outros_contratos(classe: str, campo: str) -> None:
    from src.agents import contracts as c

    if classe == "ResultadoPesquisa":
        with pytest.raises(ValidationError):
            c.ResultadoPesquisa(request_id="r", status="suficiente", motivo="inventado")
    elif classe == "EvidenciaWeb":
        with pytest.raises(ValidationError):
            c.EvidenciaWeb(
                evidence_id="e",
                url_validada="https://x.test/a",
                publicador="p",
                data_acesso="2026-11-16",
                trecho="t",
                snapshot_hash="h",
                device_id="lmp/art22",
            )
    else:
        with pytest.raises(ValidationError):
            c.RespostaConversa(kind="social", texto="x", verificacao={"semantica": "ok"})


def test_proveniencia_nao_pode_se_disfarcar_de_web() -> None:
    """Achado 1 da revisão: 'kind' estava selado, mas 'proveniencia' era texto livre."""
    from src.agents.contracts import EvidenciaBase

    with pytest.raises(ValidationError):
        EvidenciaBase(
            evidence_id="e1", device_id="lmp/art22", norm_version_id=7, proveniencia="web"
        )


def test_web_exige_allowlist() -> None:
    """Achado 2: permitir_web sem fontes_permitidas contradiz o ADR-09."""
    from src.agents.contracts import PoliticaPesquisa

    with pytest.raises(ValidationError):
        PoliticaPesquisa(permitir_web=True)
    assert PoliticaPesquisa(permitir_web=True, fontes_permitidas=("planalto.gov.br",))


@pytest.mark.parametrize(
    "url",
    ["javascript:alert(1)", "file:///C:/Windows/win.ini", "data:text/html,<b>x", "sem-host"],
)
def test_url_validada_recusa_esquema_perigoso(url: str) -> None:
    """Achado 3: o campo se chama 'url_validada' e não validava nada."""
    from src.agents.contracts import EvidenciaWeb

    with pytest.raises(ValidationError):
        EvidenciaWeb(
            evidence_id="e",
            url_validada=url,
            publicador="p",
            data_acesso="2026-11-16",
            trecho="t",
            snapshot_hash="h",
        )


def test_url_validada_aceita_https() -> None:
    from src.agents.contracts import EvidenciaWeb

    ev = EvidenciaWeb(
        evidence_id="e",
        url_validada="https://www.planalto.gov.br/ccivil_03/leis/l11340.htm",
        publicador="Planalto",
        data_acesso="2026-11-16",
        trecho="t",
        snapshot_hash="h",
    )
    assert ev.url_validada.startswith("https://")


@pytest.mark.parametrize(
    "status,extra_campo",
    [
        ("suficiente", {"erro_tipado": "timeout"}),
        ("suficiente", {"esclarecimento_necessario": "?"}),
        ("erro", {"esclarecimento_necessario": "?"}),
        ("precisa_esclarecimento", {"erro_tipado": "x"}),
    ],
)
def test_coerencia_de_status_e_bidirecional(status: str, extra_campo: dict) -> None:
    """Achado 6: o validador só cobria uma direção."""
    from src.agents.contracts import ResultadoPesquisa

    base = {"request_id": "r", "status": status}
    if status == "erro":
        base["erro_tipado"] = "timeout"
    if status == "precisa_esclarecimento":
        base["esclarecimento_necessario"] = "quando?"
    base.update(extra_campo)
    with pytest.raises(ValidationError):
        ResultadoPesquisa(**base)


@pytest.mark.parametrize(
    "campo,valor",
    [("max_buscas", 11), ("max_evidencias", 21), ("orcamento_restante", -1)],
)
def test_limites_da_politica_sao_impostos(campo: str, valor: int) -> None:
    """Achado 5: nenhum teste cobria os limites de PoliticaPesquisa."""
    from src.agents.contracts import PoliticaPesquisa

    with pytest.raises(ValidationError):
        PoliticaPesquisa(**{campo: valor})


@pytest.mark.parametrize(
    "kind", ["juridica", "esclarecimento", "social", "abstencao", "falha_tecnica"]
)
def test_todos_os_cinco_kinds_sao_aceitos(kind: str) -> None:
    """Achado 14: o nome dizia 'cinco tipos', a asserção testava um."""
    from src.agents.contracts import RespostaConversa

    ids = ["lmp/art22"] if kind == "juridica" else []
    assert RespostaConversa(kind=kind, texto="x", device_ids=ids).kind == kind


@pytest.mark.parametrize("kind", ["esclarecimento", "social", "abstencao", "falha_tecnica"])
def test_kinds_sem_citacao_recusam_device(kind: str) -> None:
    from src.agents.contracts import RespostaConversa

    with pytest.raises(ValidationError):
        RespostaConversa(kind=kind, texto="x", device_ids=["lmp/art22"])


def test_uniao_discriminada_serializa_e_revalida() -> None:
    from src.agents.contracts import ResultadoPesquisa

    original = ResultadoPesquisa(
        request_id="r-1",
        status="parcial",
        evidencias=[
            {"kind": "base", "evidence_id": "e1", "device_id": "lmp/art22", "norm_version_id": 7},
            {
                "kind": "web",
                "evidence_id": "e2",
                "url_validada": "https://www.planalto.gov.br/x",
                "publicador": "Planalto",
                "data_acesso": "2026-11-16",
                "trecho": "trecho",
                "snapshot_hash": "sha256:abc",
            },
        ],
    )
    recriado = ResultadoPesquisa.model_validate_json(original.model_dump_json())
    assert [e.kind for e in recriado.evidencias] == ["base", "web"]
