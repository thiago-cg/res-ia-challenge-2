/** Testes do cliente durável (rodam em Node, sem navegador). */
import assert from "node:assert/strict";
import test from "node:test";

import { criarClienteDuravel, novoIdMensagem } from "../../web/ui/scripts/durable.js";

function resposta(status, corpo, cabecalhos = {}) {
  return {
    ok: status >= 200 && status < 300,
    status,
    headers: new Headers(cabecalhos),
    json: async () => corpo,
    text: async () => JSON.stringify(corpo),
  };
}

test("conversa inexistente devolve null em vez de erro", async () => {
  const cliente = criarClienteDuravel("http://x", { fetchImpl: async () => resposta(404, {}) });
  assert.equal(await cliente.conversaAtual(), null);
});

test("envio repetido devolve a mesma execucao", async () => {
  const pedidos = [];
  const cliente = criarClienteDuravel("http://x", {
    fetchImpl: async (url, opcoes) => {
      pedidos.push(JSON.parse(opcoes.body));
      return resposta(pedidos.length === 1 ? 202 : 200, { run_id: "r-1", status: "queued" });
    },
  });
  const primeiro = await cliente.enviar("c-1", { mensagem: "oi", clientMessageId: "m-fixo" });
  const segundo = await cliente.enviar("c-1", { mensagem: "oi", clientMessageId: "m-fixo" });
  assert.equal(primeiro.runId, segundo.runId);
  assert.equal(segundo.repetido, true);
  assert.deepEqual(pedidos[0].client_message_id, pedidos[1].client_message_id);
});

test("o id do envio sobrevive ao retry", async () => {
  const ids = [];
  const cliente = criarClienteDuravel("http://x", {
    fetchImpl: async (url, opcoes) => {
      ids.push(JSON.parse(opcoes.body).client_message_id);
      if (ids.length === 1) throw new Error("rede caiu");
      return resposta(202, { run_id: "r-1", status: "queued" });
    },
  });
  const id = novoIdMensagem(() => "m-gerado");
  await assert.rejects(() => cliente.enviar("c-1", { mensagem: "oi", clientMessageId: id }));
  await cliente.enviar("c-1", { mensagem: "oi", clientMessageId: id });
  assert.deepEqual(ids, ["m-gerado", "m-gerado"]);
});

test("rede caiu nao vira falso sucesso", async () => {
  const cliente = criarClienteDuravel("http://x", {
    fetchImpl: async () => {
      throw new Error("offline");
    },
  });
  await assert.rejects(
    () => cliente.enviar("c-1", { mensagem: "oi", clientMessageId: "m" }),
    (erro) => erro.tipo === "rede",
  );
});

test("409 traz o run em andamento em vez de sumir", async () => {
  const cliente = criarClienteDuravel("http://x", {
    fetchImpl: async () => resposta(409, { run_id: "r-ativo", status: "running" }),
  });
  await assert.rejects(
    () => cliente.enviar("c-1", { mensagem: "oi", clientMessageId: "m" }),
    (erro) => erro.tipo === "conflito" && erro.runId === "r-ativo",
  );
});

test("304 nao perde o estado e aguardar devolve o resultado publicado", async () => {
  const chamadas = [];
  let rodada = 0;
  const cliente = criarClienteDuravel("http://x", {
    fetchImpl: async (url) => {
      chamadas.push(url);
      if (url.includes("/result")) return resposta(200, { resposta: "ok", abstencao: false });
      rodada += 1;
      if (rodada === 1) return resposta(200, { status: "running", revision: 1, events: [] });
      if (rodada === 2) return resposta(304, null);
      return resposta(200, { status: "succeeded", revision: 2, events: [] });
    },
    espera: async () => {},
  });
  const publicado = await cliente.aguardar("c-1", "r-1");
  assert.equal(publicado.resposta, "ok");
  assert.ok(chamadas.some((u) => u.includes("since=1")));
});

test("execucao que falha levanta erro tipado", async () => {
  const cliente = criarClienteDuravel("http://x", {
    fetchImpl: async () => resposta(200, { status: "failed", revision: 2, events: [] }),
    espera: async () => {},
  });
  await assert.rejects(() => cliente.aguardar("c-1", "r-1"), (erro) => erro.tipo === "failed");
});
