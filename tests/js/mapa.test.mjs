/** Funções puras do mapa (rodam em Node; o Leaflet só é carregado no navegador). */
import assert from "node:assert/strict";
import test from "node:test";

import { agruparPorPonto, rotuloCentro } from "../../web/ui/scripts/mapa.js";

test("o rótulo do centro da cidade fica curto e sem a UF", () => {
  assert.equal(rotuloCentro("centro aproximado de Guará/DF"), "Centro de Guará");
  assert.equal(rotuloCentro("centro de Brasília/DF"), "Centro de Brasília");
  assert.equal(rotuloCentro("local informado em DF"), "Centro de local informado em DF");
});

test("serviços no mesmo ponto viram um pino só, com os dois números", () => {
  const a = { nome: "12ª DP", latitude: -15.8333, longitude: -48.0556 };
  const b = { nome: "21ª DP", latitude: -15.83331, longitude: -48.05561 }; // ~1 m de a
  const c = { nome: "17ª DP", latitude: -15.8, longitude: -48.1 };
  const grupos = agruparPorPonto([a, b, c]);
  assert.equal(grupos.length, 2);
  assert.deepEqual(grupos[0].itens.map((i) => i.indice), [0, 1]);
  assert.deepEqual(grupos[1].itens.map((i) => i.indice), [2]);
});
