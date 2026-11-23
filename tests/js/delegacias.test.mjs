/** Testes das funções puras do painel de delegacias (rodam em Node, sem navegador). */
import assert from "node:assert/strict";
import test from "node:test";

import {
  arredondarCoordenada,
  calcularEsquema,
  deamSeparada,
  direcaoTexto,
  formatarDistancia,
  linkComoChegar,
  passoDoAnel,
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

test("os anéis do esquema têm no máximo 3 por raio", () => {
  assert.equal(passoDoAnel(2), 1);
  assert.equal(passoDoAnel(12), 5);
  assert.equal(passoDoAnel(40), 25);
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

test("o esquema põe o norte para cima e a origem no centro", () => {
  const origem = { lat: -15.8, lon: -47.9 };
  const servicos = [
    { nome: "ao norte", latitude: -15.7, longitude: -47.9 },
    { nome: "a leste", latitude: -15.8, longitude: -47.8 },
  ];
  const { pontos, aneis } = calcularEsquema(origem, servicos);
  assert.ok(pontos[0].y < 0 && Math.abs(pontos[0].x) < 1e-6, "norte = y negativo (para cima)");
  assert.ok(pontos[1].x > 0 && Math.abs(pontos[1].y) < 1e-6, "leste = x positivo");
  assert.ok(aneis.length >= 1 && aneis.length <= 4);
});
