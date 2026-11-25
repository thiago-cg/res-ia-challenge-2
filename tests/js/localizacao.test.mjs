import assert from "node:assert/strict";
import test from "node:test";

import { classificarPermissao } from "../../web/ui/scripts/localizacao.js";

test("estados conhecidos do navegador são mantidos", () => {
  assert.equal(classificarPermissao("granted"), "granted");
  assert.equal(classificarPermissao("prompt"), "prompt");
  assert.equal(classificarPermissao("denied"), "denied");
});

test("estado desconhecido vira 'pergunta ao usar'", () => {
  assert.equal(classificarPermissao("qualquer-coisa"), "unknown");
  assert.equal(classificarPermissao(undefined), "unknown");
});

test("sem geolocalização o aparelho é tratado como indisponível", () => {
  assert.equal(classificarPermissao("granted", false), "unsupported");
});
