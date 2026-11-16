from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

from scripts import import_osm_police as imp
from scripts.load_services import UPSERT
from src.services.osm import classificar, consulta_overpass, deduplicar, elemento_para_linha


def no(id_: int, lat: float, lon: float, **tags: str) -> dict:
    return {"type": "node", "id": id_, "lat": lat, "lon": lon, "tags": tags}


@pytest.mark.parametrize(
    ("tags", "esperado"),
    [
        ({"name": "Delegacia Especial de Atendimento à Mulher"}, "deam"),
        ({"name": "DEAM Ceilândia"}, "deam"),
        ({"name": "Delegacia da Mulher de Goiânia"}, "deam"),
        ({"name": "Núcleo Integrado de Atendimento à Mulher"}, "nucleo_atendimento_mulher"),
        ({"name": "6ª Delegacia de Polícia"}, "delegacia_comum"),
        ({"name": "15ª DP - Ceilândia"}, "delegacia_comum"),
        (
            {"name": "Posto policial", "operator": "Polícia Civil do Estado de Goiás"},
            "delegacia_comum",
        ),
        # Outras forças e órgãos que também são amenity=police no OSM:
        ({"name": "Batalhão de Polícia Militar"}, None),
        ({"name": "Polícia Militar - Posto Comunitário"}, None),
        ({"name": "Polícia Rodoviária Federal"}, None),
        ({"name": "Delegacia de Polícia Federal"}, None),
        ({"name": "Guarda Municipal"}, None),
        ({"name": "Instituto de Criminalística"}, None),
        ({"name": "Delegacia", "operator": "Polícia Militar"}, None),
        ({}, None),  # sem nome: não dá para mostrar
        ({"name": "Praça da Matriz"}, None),
    ],
)
def test_classificacao_por_nome(tags: dict[str, str], esperado: str | None) -> None:
    assert classificar(tags) == esperado


def test_linha_completa_de_um_ponto() -> None:
    elemento = no(
        42,
        -16.68,
        -49.25,
        name="Delegacia Estadual de Atendimento à Mulher",
        **{"addr:street": "Rua 7", "addr:housenumber": "100", "addr:suburb": "Setor Central"},
        phone="+55 62 3201-0000; 190",
        opening_hours="24/7",
        **{"addr:city": "Goiânia"},
    )

    linha = elemento_para_linha(elemento, "GO", hoje=date(2026, 11, 16))

    assert linha == {
        "uf": "GO",
        "municipio": "Goiânia",
        "nome": "Delegacia Estadual de Atendimento à Mulher",
        "tipo": "deam",
        "endereco": "Rua 7, 100 - Setor Central",
        "telefone": "+55 62 3201-0000",
        "horario": "24 horas",
        "latitude": -16.68,
        "longitude": -49.25,
        "coordenada_verificada": True,
        "origem": "osm",
        "fonte_url": "https://www.openstreetmap.org/node/42",
        "atualizado_em": date(2026, 11, 16),
    }


def test_predio_usa_o_centro_e_municipio_vem_do_mais_proximo_quando_falta() -> None:
    predio = {
        "type": "way",
        "id": 7,
        "center": {"lat": -23.55, "lon": -46.63},
        "tags": {"name": "1º Distrito Policial"},
    }

    linha = elemento_para_linha(predio, "SP")

    assert linha is not None
    assert linha["municipio"] == "São Paulo"
    assert linha["telefone"] is None and linha["horario"] is None
    assert linha["fonte_url"].endswith("/way/7")


def test_sem_coordenada_e_descartado() -> None:
    assert (
        elemento_para_linha({"type": "relation", "id": 1, "tags": {"name": "1ª DP"}}, "SP") is None
    )


def test_telefone_curto_demais_nao_vira_telefone() -> None:
    elemento = no(1, -23.5, -46.6, name="2ª Delegacia de Polícia", phone="190")
    assert elemento_para_linha(elemento, "SP")["telefone"] is None  # type: ignore[index]


def test_deduplica_ponto_e_predio_do_mesmo_posto_e_curadas() -> None:
    a = elemento_para_linha(
        no(1, -16.680, -49.250, name="DEAM Goiânia", phone="62 3201-0000"), "GO"
    )
    b = elemento_para_linha(no(2, -16.6802, -49.2501, name="DEAM Goiânia"), "GO")  # mesmo lugar
    c = elemento_para_linha(no(3, -16.70, -49.30, name="1ª Delegacia de Polícia"), "GO")
    d = elemento_para_linha(no(4, -16.70, -49.30, name="DEAM Anápolis"), "GO")  # classe diferente

    unicas = deduplicar([a, b, c, d])  # type: ignore[list-item]
    assert sorted(r["nome"] for r in unicas) == [
        "1ª Delegacia de Polícia",
        "DEAM Anápolis",
        "DEAM Goiânia",
    ]
    assert next(r for r in unicas if r["nome"] == "DEAM Goiânia")[
        "telefone"
    ]  # ficou a com telefone

    curada = [(-16.6805, -49.2502, "deam")]
    sobra = deduplicar([a, c], existentes=curada)  # type: ignore[list-item]
    assert [r["nome"] for r in sobra] == ["1ª Delegacia de Polícia"]


def test_upsert_nao_sobrescreve_dado_de_outra_origem() -> None:
    assert "WHERE services.origem = EXCLUDED.origem" in UPSERT


def test_consulta_overpass_filtra_estado_e_policia() -> None:
    q = consulta_overpass("GO")
    assert "BR-GO" in q and '"amenity"="police"' in q and "out center tags" in q


def test_script_offline_dry_run_le_os_arquivos_sem_rede(
    tmp_path: Path, capsys, monkeypatch
) -> None:
    (tmp_path / "GO.json").write_text(
        json.dumps(
            {
                "elements": [
                    no(1, -16.68, -49.25, name="DEAM Goiânia", **{"addr:city": "Goiânia"}),
                    no(2, -16.70, -49.30, name="1ª Delegacia de Polícia"),
                    no(3, -16.71, -49.31, name="Batalhão de Polícia Militar"),
                ]
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.delenv("DATABASE_URL", raising=False)

    codigo = imp.main(["--uf", "GO", "--from-dir", str(tmp_path), "--offline", "--dry-run"])

    saida = capsys.readouterr().out
    assert codigo == 0
    assert "GO: 2 delegacia(s), 1 de atendimento à mulher" in saida
    assert "2 delegacia(s) encontrada(s)" in saida


def test_script_offline_sem_arquivo_falha_so_aquele_estado(tmp_path: Path, capsys) -> None:
    codigo = imp.main(["--uf", "AC", "--from-dir", str(tmp_path), "--offline", "--dry-run"])

    assert codigo == 1 and "Falharam: AC" in capsys.readouterr().out


def test_script_recusa_uf_invalida() -> None:
    with pytest.raises(SystemExit):
        imp.main(["--uf", "XX", "--dry-run"])


def test_erro_de_certificado_falha_na_hora_sem_repetir(monkeypatch, capsys) -> None:
    import ssl
    import urllib.error

    chamadas = []

    def falha(*args, **kwargs):
        chamadas.append(1)
        raise urllib.error.URLError(ssl.SSLCertVerificationError("unable to get local issuer"))

    monkeypatch.setattr(imp.urllib.request, "urlopen", falha)
    monkeypatch.setattr(imp.time, "sleep", lambda s: pytest.fail("não deve esperar"))

    codigo = imp.main(["--uf", "DF", "GO", "--from-dir", "/tmp/nao-existe-osm", "--dry-run"])

    assert codigo == 2 and len(chamadas) == 1  # parou no primeiro estado
    assert "truststore" in capsys.readouterr().out


def test_servidor_ocupado_ainda_repete(monkeypatch) -> None:
    import urllib.error

    esperas = []
    respostas = [urllib.error.HTTPError("u", 504, "busy", {}, None), None]

    class Resp:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return b'{"elements": []}'

    def urlopen(*args, **kwargs):
        item = respostas.pop(0)
        if item is not None:
            raise item
        return Resp()

    monkeypatch.setattr(imp.urllib.request, "urlopen", urlopen)
    monkeypatch.setattr(imp.time, "sleep", esperas.append)

    assert imp.baixar_estado("DF", "https://exemplo") == {"elements": []}
    assert esperas == [30]


def test_instancia_recusa_e_a_proxima_atende_sem_esperar(monkeypatch, capsys) -> None:
    import urllib.error

    visitadas = []

    class Resp:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return b'{"elements": []}'

    def urlopen(pedido, *args, **kwargs):
        visitadas.append(pedido.full_url)
        if "primeira" in pedido.full_url:
            raise urllib.error.HTTPError(pedido.full_url, 429, "too many", {}, None)
        return Resp()

    monkeypatch.setattr(imp.urllib.request, "urlopen", urlopen)
    monkeypatch.setattr(imp.time, "sleep", lambda s: pytest.fail("não deve esperar"))

    resultado = imp.baixar_estado("DF", ["https://primeira.exemplo/x", "https://segunda.exemplo/x"])

    assert resultado == {"elements": []} and len(visitadas) == 2


def test_todas_recusam_mostra_o_motivo_de_cada_uma(monkeypatch, capsys) -> None:
    import urllib.error

    def urlopen(pedido, *args, **kwargs):
        raise urllib.error.HTTPError(pedido.full_url, 429, "too many", {}, None)

    monkeypatch.setattr(imp.urllib.request, "urlopen", urlopen)
    monkeypatch.setattr(imp.time, "sleep", lambda s: None)

    with pytest.raises(imp.ErroOverpass) as erro:
        imp.baixar_estado("DF", ["https://a.exemplo/x", "https://b.exemplo/x"])

    assert "a.exemplo: HTTP 429" in str(erro.value) and "b.exemplo: HTTP 429" in str(erro.value)
    assert "a.exemplo: HTTP 429" in capsys.readouterr().out
