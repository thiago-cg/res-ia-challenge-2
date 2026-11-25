import assert from "node:assert/strict";
import test from "node:test";

import { ErroPin, ITERACOES_PIN, criarMeta, destrancar, selar, abrirSelo, validarPin } from "../../web/ui/scripts/cofre-cripto.js";
import { ErroEspera, criarArmazemMemoria, criarCofre } from "../../web/ui/scripts/cofre.js";
import { escaparHtml, montarRelatorio } from "../../web/ui/scripts/relatorio.js";

// 1.000 voltas bastam para provar a lógica; a constante real (600 mil) é checada à parte.
const ITER_TESTE = 1000;

const conversa = {
  fuso: "America/Sao_Paulo",
  fatos: { data_fato: "2026-11-01" },
  mensagens: [
    { papel: "usuario", texto: "Ele me ameaçou hoje.", em: "2026-11-25T17:02:11.000Z" },
    {
      papel: "assistente",
      em: "2026-11-25T17:02:15.000Z",
      resposta: { resposta: "Sinto muito. Em perigo, ligue 190.", citacoes: [{ citacao: "Lei 11.340/2006, art. 12", fonte_url: "https://exemplo.gov.br" }], nivel_confianca: "alto", emergencia: true },
    },
  ],
};

test("a constante de voltas do PIN é a recomendada (600 mil)", () => {
  assert.equal(ITERACOES_PIN, 600_000);
});

test("validarPin: 6 a 12 números, sem repetição nem sequência", () => {
  assert.equal(validarPin("483920"), null);
  assert.match(validarPin("1234"), /6 a 12/);
  assert.match(validarPin("12345a"), /6 a 12/);
  assert.match(validarPin("111111"), /repetir/);
  assert.match(validarPin("123456"), /sequência/);
  assert.match(validarPin("987654"), /sequência/);
});

test("selar e abrir: ida e volta, e o PIN errado não abre", async () => {
  const meta = await criarMeta("483920", { iteracoes: ITER_TESTE });
  const selo = await selar(meta.chavePublica, { oi: "mundo" });
  assert.ok(!JSON.stringify(selo).includes("mundo"));
  const privada = await destrancar(meta, "483920");
  assert.deepEqual(await abrirSelo(privada, selo), { oi: "mundo" });
  await assert.rejects(() => destrancar(meta, "000019"), ErroPin);
});

test("registro adulterado é rejeitado (AES-GCM)", async () => {
  const meta = await criarMeta("483920", { iteracoes: ITER_TESTE });
  const selo = await selar(meta.chavePublica, { a: 1 });
  const bytes = Buffer.from(selo.dados, "base64");
  bytes[0] ^= 1;
  const privada = await destrancar(meta, "483920");
  await assert.rejects(() => abrirSelo(privada, { ...selo, dados: bytes.toString("base64") }));
});

test("arquivar não precisa do PIN, e só o PIN certo lê", async () => {
  const cofre = criarCofre({ armazem: criarArmazemMemoria(), iteracoes: ITER_TESTE });
  assert.equal(await cofre.existe(), false);
  await assert.rejects(() => cofre.arquivar(conversa), /ainda não foi criada/);
  await cofre.criar("483920");
  const id = await cofre.arquivar(conversa);
  const sessao = await cofre.desbloquear("483920");
  const lista = await sessao.listar();
  assert.equal(lista.length, 1);
  assert.equal(lista[0].total, 2);
  assert.equal(lista[0].perguntas, 1);
  const { registro, integro } = await sessao.obter(id);
  assert.equal(integro, true);
  assert.equal(registro.mensagens[0].texto, "Ele me ameaçou hoje.");
  assert.equal(registro.fatos.data_fato, "2026-11-01");
});

test("nada legível fica guardado em claro", async () => {
  const armazem = criarArmazemMemoria();
  const cofre = criarCofre({ armazem, iteracoes: ITER_TESTE });
  await cofre.criar("483920");
  await cofre.arquivar(conversa);
  const bruto = JSON.stringify({ meta: await armazem.lerMeta(), registros: await armazem.listar() });
  for (const segredo of ["ameaçou", "11.340", "Sinto muito", "483920"]) assert.ok(!bruto.includes(segredo), segredo);
});

test("PIN errado: cinco erros e passa a exigir espera", async () => {
  let agora = new Date("2026-11-25T12:00:00Z");
  const cofre = criarCofre({ armazem: criarArmazemMemoria(), iteracoes: ITER_TESTE, agora: () => agora });
  await cofre.criar("483920");
  for (let i = 0; i < 4; i += 1) await assert.rejects(() => cofre.desbloquear("000019"), ErroPin);
  await assert.rejects(() => cofre.desbloquear("000019"), ErroEspera);
  await assert.rejects(() => cofre.desbloquear("483920"), ErroEspera); // até o certo espera
  agora = new Date(agora.getTime() + 31_000);
  const sessao = await cofre.desbloquear("483920");
  assert.equal(sessao.aberta, true);
});

test("bloquear fecha a sessão", async () => {
  const cofre = criarCofre({ armazem: criarArmazemMemoria(), iteracoes: ITER_TESTE });
  await cofre.criar("483920");
  await cofre.arquivar(conversa);
  const sessao = await cofre.desbloquear("483920");
  sessao.bloquear();
  assert.equal(sessao.aberta, false);
  await assert.rejects(() => sessao.listar(), /trancada/);
});

test("trocar o PIN mantém os registros legíveis", async () => {
  const cofre = criarCofre({ armazem: criarArmazemMemoria(), iteracoes: ITER_TESTE });
  await cofre.criar("483920");
  const id = await cofre.arquivar(conversa);
  const sessao = await cofre.desbloquear("483920");
  await sessao.trocarPin("483920", "271845");
  await assert.rejects(() => cofre.desbloquear("483920"), ErroPin);
  const nova = await cofre.desbloquear("271845");
  assert.equal((await nova.obter(id)).integro, true);
});

test("apagar tudo remove a pasta", async () => {
  const cofre = criarCofre({ armazem: criarArmazemMemoria(), iteracoes: ITER_TESTE });
  await cofre.criar("483920");
  await cofre.arquivar(conversa);
  await cofre.apagarTudo();
  assert.equal(await cofre.existe(), false);
});

test("relatório: dia e hora no fuso, hash e nada executável", async () => {
  const cofre = criarCofre({ armazem: criarArmazemMemoria(), iteracoes: ITER_TESTE });
  await cofre.criar("483920");
  const hostil = {
    ...conversa,
    mensagens: [{ papel: "usuario", texto: '<img src=x onerror="alert(1)"><script>x()</script>', em: "2026-11-25T17:02:11.000Z" }],
  };
  const id = await cofre.arquivar(hostil);
  const sessao = await cofre.desbloquear("483920");
  const { registro, integro } = await sessao.obter(id);
  const r = montarRelatorio(registro, { integro, geradoEm: new Date("2026-12-01T12:00:00Z") });
  assert.match(r.html, /25\/11\/2026 às 14:02:11/); // 17:02Z em São Paulo (UTC-3)
  assert.ok(r.html.includes(registro.hash));
  assert.ok(!r.html.includes("<img src=x"));
  assert.ok(!/<script>x\(\)/.test(r.html));
  assert.ok(r.html.includes("&#60;script&#62;"));
  assert.match(r.texto, /SHA-256/);
  assert.equal(escaparHtml('<a href="x">&</a>'), "&#60;a href=&#34;x&#34;&#62;&#38;&#60;/a&#62;");
});

test("relatório sem horário não inventa um", () => {
  const r = montarRelatorio({ fuso: "UTC", mensagens: [{ papel: "usuario", texto: "oi", em: null }], hash: "abc", arquivadoEm: "2026-11-25T10:00:00Z", fatos: {} });
  assert.match(r.texto, /horário não registrado/);
});
