/** Testes das funções puras do painel de delegacias (rodam em Node, sem navegador). */
import assert from "node:assert/strict";
import test from "node:test";

import {
  arredondarCoordenada,
  deamSeparada,
  estadoPermissao,
  origemDaPosicao,
  origemDaResposta,
  pedirPosicao,
  semDuplicatas,
  servicosOrdenados,
  direcaoTexto,
  formatarDistancia,
  linkComoChegar,
  rotuloDistancia,
  telefoneParaLink,
} from "../../web/ui/scripts/delegacias.js";

test("a posição é arredondada a ~110 m antes de sair do navegador", () => {
  assert.equal(arredondarCoordenada(-15.79391), -15.794);
  assert.equal(arredondarCoordenada(-47.88282), -47.883);
});

test("distância curta vira metros e distância longa vira km", () => {
  assert.equal(formatarDistancia(0.5), "500 m");
  assert.equal(formatarDistancia(1.9), "1,9 km");
  assert.equal(formatarDistancia(12.3), "12 km");
  assert.equal(formatarDistancia(null), "");
  assert.equal(formatarDistancia(undefined), "");
});

test("ponto aproximado a menos de 1 km mostra 'na região', não metros", () => {
  const aproximado = { distancia_km: 0.001, coordenada_verificada: false };
  assert.equal(rotuloDistancia(aproximado), "na região");
  assert.equal(rotuloDistancia({ distancia_km: 0.9, coordenada_verificada: false }), "na região");
});

test("ponto verificado mantém metros, e ponto aproximado distante mantém km", () => {
  assert.equal(rotuloDistancia({ distancia_km: 0.5, coordenada_verificada: true }), "500 m");
  assert.equal(rotuloDistancia({ distancia_km: 1.9, coordenada_verificada: false }), "1,9 km");
  assert.equal(rotuloDistancia({ distancia_km: 7.8, coordenada_verificada: false }), "7,8 km");
});

test("direção em texto segue os pontos cardeais, sem direção quando está no mesmo lugar", () => {
  assert.equal(direcaoTexto({ leste: 0, norte: 5 }), "ao norte");
  assert.equal(direcaoTexto({ leste: 5, norte: 0 }), "a leste");
  assert.equal(direcaoTexto({ leste: -3, norte: 3 }), "ao noroeste");
  assert.equal(direcaoTexto({ leste: 0.001, norte: 0.001 }), "");
});

test("telefone vira link tel: e número vazio não gera link", () => {
  assert.equal(telefoneParaLink("(61) 3207-7391"), "tel:6132077391");
  assert.equal(telefoneParaLink(""), "");
  assert.equal(telefoneParaLink(null), "");
});

test("'Como chegar' leva só o destino, nunca a posição da usuária", () => {
  const link = linkComoChegar({
    nome: "14ª DP – Gama",
    endereco: "Área Especial 01, Setor Central",
    municipio: "Brasília",
    uf: "DF",
  });
  assert.ok(link.startsWith("https://www.google.com/maps/search/?api=1&query="));
  assert.ok(decodeURIComponent(link).includes("14ª DP – Gama"));
  assert.ok(!/origin|lat|lon/i.test(link));
});

test("a DEAM mais próxima só aparece à parte quando não está na lista", () => {
  const deam = { nome: "DEAM I", endereco: "EQS 204/205" };
  assert.equal(deamSeparada({ servicos: [deam], deam_mais_proxima: deam }), null);
  assert.deepEqual(deamSeparada({ servicos: [], deam_mais_proxima: deam }), deam);
  assert.equal(deamSeparada({ servicos: [] }), null);
});

test("sem a API de permissões, a localização é tratada como 'prompt'", async () => {
  assert.equal(await estadoPermissao(), "prompt");
});

test("a lista é uma só, por proximidade; a DEAM entra pela distância e nunca fica de fora", () => {
  const dp = (nome, km) => ({ nome, tipo: "delegacia_comum", distancia_km: km, endereco: nome });
  const deam = { nome: "DEAM I", tipo: "deam", distancia_km: 8, endereco: "EQS 204/205" };
  // Guará: a DEAM está além das 5 mais próximas e vem separada pela API.
  const guara = servicosOrdenados({
    servicos: [dp("a", 0.4), dp("b", 4.6), dp("c", 6), dp("d", 7), dp("e", 9)],
    deam_mais_proxima: deam,
  });
  assert.deepEqual(guara.map((s) => s.nome), ["a", "b", "c", "d", "DEAM I", "e"]);
  // Gama: a DEAM já está na lista; não duplica.
  const gama = servicosOrdenados({ servicos: [dp("a", 0.5), deam, dp("b", 9)], deam_mais_proxima: deam });
  assert.deepEqual(gama.map((s) => s.nome), ["a", "DEAM I", "b"]);
  // Busca por estado (sem distância): mantém a ordem da API e acrescenta a DEAM no fim.
  const estado = servicosOrdenados({
    servicos: [{ nome: "x", tipo: "delegacia_comum", distancia_km: null }],
    deam_mais_proxima: { nome: "DEAM", tipo: "deam", distancia_km: null },
  });
  assert.deepEqual(estado.map((s) => s.nome), ["x", "DEAM"]);
});

test("Núcleo e DP do mesmo número no mesmo lugar viram um cartão só (o Núcleo)", () => {
  const dp = { nome: "11ª DP – Núcleo Bandeirante", tipo: "delegacia_comum", uf: "DF", latitude: -15.872, longitude: -47.969, distancia_km: 4.6 };
  const nucleo = { nome: "11ª Delegacia de Polícia (Núcleo Bandeirante) - Núcleo Integrado", tipo: "nucleo_atendimento_mulher", uf: "DF", latitude: -15.872, longitude: -47.969, distancia_km: 4.6 };
  const outra = { nome: "12ª DP – Taguatinga Norte", tipo: "delegacia_comum", uf: "DF", latitude: -15.83, longitude: -48.05, distancia_km: 6 };
  assert.deepEqual(semDuplicatas([dp, nucleo, outra]).map((s) => s.tipo), ["nucleo_atendimento_mulher", "delegacia_comum"]);
  // outro número no mesmo ponto não é duplicata
  assert.equal(semDuplicatas([{ ...dp, nome: "10ª DP – Lago Sul" }, nucleo]).length, 2);
});

test("o pino usa a posição exata; a consulta à API usa a arredondada", () => {
  const origem = origemDaPosicao({ coords: { latitude: -15.833361, longitude: -47.983347, accuracy: 18.4 } });
  assert.equal(origem.lat, -15.833);
  assert.equal(origem.lon, -47.983);
  const pino = origemDaResposta({}, origem);
  assert.equal(pino.lat, -15.833361);
  assert.equal(pino.lon, -47.983347);
  assert.equal(pino.precisao, 18.4);
  assert.equal(pino.rotulo, "você");
});

test("tenta o GPS primeiro e cai para posição aproximada; negar não tenta de novo", async () => {
  const chamadas = [];
  const gps = {
    getCurrentPosition(ok, erro, opcoes) {
      chamadas.push(opcoes.enableHighAccuracy);
      if (opcoes.enableHighAccuracy) erro({ code: 3 });
      else ok({ coords: { latitude: 1, longitude: 2, accuracy: 900 } });
    },
  };
  const posicao = await pedirPosicao(gps);
  assert.equal(posicao.coords.accuracy, 900);
  assert.deepEqual(chamadas, [true, false]);

  const negado = { getCurrentPosition: (ok, erro) => erro({ code: 1 }) };
  await assert.rejects(() => pedirPosicao(negado), { code: 1 });
});
