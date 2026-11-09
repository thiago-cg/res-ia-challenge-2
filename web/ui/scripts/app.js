/**
 * ZELIA · interface do chatbot
 *
 * Estado em memória; persistência opcional e local. Toda saída da API é
 * tratada como dado: o texto passa por markdown.js (que escapa antes de
 * formatar) e as URLs só são usadas depois de validadas.
 */

import { criarCliente } from "./api.js";
import { escapar, markdown } from "./markdown.js";
import { EXEMPLOS, EXEMPLO_EMERGENCIA, RESPOSTAS_DEMO, respostaDemo } from "./demo.js";

const CHAVE_HISTORICO = "zelia.historico.v1";
const CHAVE_PREFERENCIAS = "zelia.preferencias.v1";
const CHAVE_SESSAO = "zelia.sessao";
const LIMITE_MENSAGENS = 40;
const LIMITE_CARACTERES = 8000;

const SIMBOLO = `<svg viewBox="177.379 170.097 237.238 214.644" aria-hidden="true" focusable="false"><path pathLength="1" d="M 199.166 207.216 C 252.424 194.305 305.681 191.884 358.939 199.953 C 384.761 203.181 391.216 214.478 378.305 233.844 L 213.691 320.993 C 200.78 340.36 207.235 351.657 233.057 354.884 C 286.315 362.954 339.572 360.533 392.83 347.622"/></svg>`;

const ICONES_ENCAMINHAMENTO = {
  policia: { nome: "Polícia", icone: "escudo", telefone: "190" },
  central_mulher: { nome: "Central de Atendimento à Mulher", icone: "telefone", telefone: "180" },
  direitos_humanos: { nome: "Direitos Humanos", icone: "telefone", telefone: "100" },
  policia_civil: { nome: "Polícia Civil", icone: "escudo", telefone: "197" },
  deam: { nome: "Delegacia da Mulher", icone: "mapa", telefone: "" },
  defensoria: { nome: "Defensoria Pública", icone: "balanca", telefone: "" },
  casa_mulher: { nome: "Casa da Mulher Brasileira", icone: "mapa", telefone: "" },
  cras: { nome: "CRAS", icone: "mapa", telefone: "" },
  creas: { nome: "CREAS", icone: "mapa", telefone: "" },
  saude: { nome: "Serviço de saúde", icone: "mapa", telefone: "" },
};

const ROTULOS_CONFIANCA = {
  alto: "Confiança alta",
  medio: "Confiança média",
  baixo: "Confiança baixa",
};

const MOTIVOS_ABSTENCAO = {
  erro_recuperacao: "Não foi possível consultar a base agora. Os caminhos abaixo continuam válidos.",
  falha_na_recuperacao: "A consulta à base falhou neste momento. Os caminhos abaixo continuam válidos.",
  nenhum_dispositivo_recuperado: "Nenhum dispositivo da base corresponde a esta pergunta.",
  "nenhum dispositivo recuperado": "Nenhum dispositivo da base corresponde a esta pergunta.",
  citacao_explicita_nao_encontrada:
    "O artigo citado não foi encontrado na versão consultada da base.",
  citacao_explicita_sem_versao_vigente:
    "O artigo citado não tem versão vigente na data considerada.",
  contexto_incompleto: "Faltou contexto para responder com segurança.",
  verificacao_falhou: "A resposta não passou na verificação de fidelidade às fontes.",
  servico_indisponivel: "O serviço de resposta está indisponível agora.",
  fora_do_corpus: "A pergunta está fora do que a base cobre.",
};

const estado = {
  mensagens: [],
  sessao: "",
  dataFato: "",
  historico: false,
  modo: "api",
  ocupado: false,
  saude: null,
  api: null,
};

const el = {};
let sequencia = 0;
let confirmandoExclusao = false;
let timerConfirmacao = 0;

/* --- utilidades ---------------------------------------------------------- */

function icone(nome, classeExtra = "") {
  return `<svg class="i ${classeExtra}" aria-hidden="true" focusable="false"><use href="#i-${nome}"></use></svg>`;
}

function noDeHtml(html) {
  const modelo = document.createElement("template");
  modelo.innerHTML = String(html).trim();
  return modelo.content.firstElementChild;
}

function urlSegura(valor) {
  try {
    const url = new URL(String(valor), window.location.href);
    return url.protocol === "http:" || url.protocol === "https:" ? url.href : "";
  } catch {
    return "";
  }
}

function formatarData(iso) {
  if (!iso) return "";
  const texto = String(iso).slice(0, 10);
  const partes = texto.split("-");
  if (partes.length !== 3) return texto;
  const [ano, mes, dia] = partes;
  if (!/^\d{4}$/.test(ano) || !/^\d{2}$/.test(mes) || !/^\d{2}$/.test(dia)) return texto;
  return `${dia}/${mes}/${ano}`;
}

function anunciar(texto) {
  let regiao = document.getElementById("anuncio");
  if (!regiao) {
    regiao = document.createElement("p");
    regiao.id = "anuncio";
    regiao.className = "sr-only";
    regiao.setAttribute("aria-live", "polite");
    document.body.appendChild(regiao);
  }
  regiao.textContent = "";
  window.setTimeout(() => {
    regiao.textContent = texto;
  }, 60);
}

const REGRAS_ENCAMINHAMENTO = [
  { teste: /policia civil|\b197\b/, nome: "Polícia Civil", icone: "escudo", telefone: "197" },
  {
    teste: /central.*mulher|\b180\b/,
    nome: "Central de Atendimento à Mulher",
    icone: "telefone",
    telefone: "180",
  },
  { teste: /direitos humanos|\b100\b/, nome: "Direitos Humanos", icone: "telefone", telefone: "100" },
  {
    teste: /policia militar|policia|\b190\b/,
    nome: "Polícia",
    icone: "escudo",
    telefone: "190",
  },
  { teste: /delegacia|deam/, nome: "Delegacia da Mulher", icone: "mapa", telefone: "" },
  { teste: /defensoria/, nome: "Defensoria Pública", icone: "balanca", telefone: "" },
  { teste: /casa da mulher/, nome: "Casa da Mulher Brasileira", icone: "mapa", telefone: "" },
  { teste: /cras|creas|assistencia social/, nome: "Assistência Social", icone: "mapa", telefone: "" },
  { teste: /saude|hospital|ubs/, nome: "Serviço de saúde", icone: "mapa", telefone: "" },
];

function semAcento(texto) {
  return String(texto || "")
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .toLowerCase();
}

/**
 * Aceita os dois formatos de encaminhamento do contrato (lista de dicts):
 * ``{tipo, descricao}`` do fallback e ``{servico, contato, quando}`` do LLM.
 */
function infoEncaminhamento(item) {
  const tipo = String(item.tipo || item.servico || item.nome || "").trim();
  const descricao = String(item.descricao || item.quando || item.observacao || "").trim();
  const contato = String(item.contato || "").trim();
  const chave = semAcento(tipo).replace(/[\s-]+/g, "_");
  const base = ICONES_ENCAMINHAMENTO[chave];
  if (base) return { ...base, descricao };

  const texto = semAcento(`${tipo} ${descricao} ${contato}`);
  const regra = REGRAS_ENCAMINHAMENTO.find((candidata) => candidata.teste.test(texto));
  const telefoneDoContato = contato.match(/^(?:tel:)?\s*(\d{3,4})$/);
  const telefone = regra?.telefone || (telefoneDoContato ? telefoneDoContato[1] : "");

  return {
    nome: regra?.nome || tipo || "Rede de apoio",
    icone: regra?.icone || "pessoas",
    telefone,
    descricao,
  };
}

/* --- abertura ------------------------------------------------------------ */

function htmlAbertura() {
  const exemplos = EXEMPLOS.map(
    (pergunta) => `
      <button class="exemplo" type="button" data-enviar="${escapar(pergunta)}">
        <span>${escapar(pergunta)}</span>
        ${icone("seta")}
      </button>`,
  ).join("");

  return `
    <section class="abertura">
      <p class="abertura__rotulo">Orientação jurídica</p>
      <h1 class="abertura__titulo">Entenda o que a lei diz, <em>no seu tempo.</em></h1>
      <p class="abertura__texto">Informação confiável, em linguagem simples, com a fonte na mão. Você decide o ritmo.</p>
      <span class="chip chip--privacidade">${icone("cadeado")} Conversa privada · nada aparece em notificações</span>

      <div class="exemplos">
        <h2 class="exemplos__titulo">Comece por onde for mais fácil</h2>
        <div class="exemplos__lista">${exemplos}</div>
      </div>

      <p class="abertura__nota">Conteúdo informativo com base na Lei 11.340/2006 e atos do CNJ. Não substitui atendimento jurídico individual. Em perigo, ligue 190.</p>
    </section>`;
}

/* --- mensagens ----------------------------------------------------------- */

function renderUsuario(texto) {
  const artigo = document.createElement("article");
  artigo.className = "mensagem mensagem--usuario";
  const bolha = document.createElement("div");
  bolha.className = "bolha bolha--usuario";
  const paragrafo = document.createElement("p");
  paragrafo.textContent = texto;
  bolha.appendChild(paragrafo);
  artigo.appendChild(bolha);
  return artigo;
}

function htmlFonte(citacao) {
  const vigenciaBruta = String(citacao.vigencia || "").toLowerCase();
  const vigencia = ["vigente", "alterado", "revogado", "cancelado", "superado"].includes(vigenciaBruta)
    ? vigenciaBruta
    : "";
  const selo = vigencia
    ? `<span class="selo-vigencia selo-vigencia--${vigencia}">${escapar(vigencia)}</span>`
    : "";
  const link = urlSegura(citacao.fonte_url);
  const acao = link
    ? `<a class="fonte__link" href="${escapar(link)}" target="_blank" rel="noopener noreferrer">Abrir a fonte oficial ${icone("link")}</a>`
    : "";

  return `
    <div class="fonte">
      <div class="fonte__topo">
        <span class="fonte__citacao">${escapar(citacao.citacao || citacao.device_id || "Fonte")}</span>
        ${selo}
      </div>
      <p class="fonte__texto">${escapar(citacao.texto || "")}</p>
      ${acao}
    </div>`;
}

function htmlFontes(citacoes) {
  const id = `fontes-${++sequencia}`;
  const rotulo = citacoes.length === 1 ? "1 referência institucional" : `${citacoes.length} referências institucionais`;

  return `
    <section class="cartao" data-aberto="true">
      <button class="cartao__cabecalho" type="button" aria-expanded="true" aria-controls="${id}">
        <span class="cartao__icone">${icone("documento")}</span>
        <span class="cartao__titulo">Fontes verificadas</span>
        <span class="cartao__meta">${rotulo}</span>
        ${icone("chevron", "cartao__chevron")}
      </button>
      <div class="cartao__corpo" id="${id}">${citacoes.map(htmlFonte).join("")}</div>
    </section>`;
}

function htmlPassos(passos, titulo = "Próximos passos") {
  const itens = passos
    .map(
      (passo, indice) => `
      <li class="passo">
        <span class="passo__numero" aria-hidden="true">${indice + 1}</span>
        <span class="passo__texto">${escapar(passo)}</span>
      </li>`,
    )
    .join("");

  return `
    <section class="passos">
      <h3 class="passos__titulo">${icone("balanca")}${escapar(titulo)}</h3>
      <ol class="passos__lista">${itens}</ol>
    </section>`;
}

function htmlAjuda(encaminhamentos) {
  const itens = encaminhamentos
    .map((item) => {
      const info = infoEncaminhamento(item);
      const telefone = info.telefone
        ? `<a class="ajuda__telefone" href="tel:${escapar(info.telefone)}">${icone("telefone")}${escapar(info.telefone)}</a>`
        : "";
      const descricao = info.descricao
        ? `<p class="ajuda__descricao">${escapar(info.descricao)}</p>`
        : "";
      return `
        <div class="ajuda__item">
          <span class="ajuda__icone">${icone(info.icone)}</span>
          <div>
            <p class="ajuda__tipo">${escapar(info.nome)}</p>
            ${descricao}
          </div>
          ${telefone}
        </div>`;
    })
    .join("");

  return `
    <section class="ajuda">
      <h3 class="ajuda__titulo">${icone("pessoas")}Onde procurar ajuda</h3>
      ${itens}
    </section>`;
}

function htmlMeta(resposta) {
  const nivel = Object.hasOwn(ROTULOS_CONFIANCA, resposta.nivel_confianca)
    ? resposta.nivel_confianca
    : "baixo";
  const data = formatarData(resposta.data_atualizacao_base);

  return `
    <div class="meta-resposta">
      <span class="confianca confianca--${nivel}">${ROTULOS_CONFIANCA[nivel]}</span>
      <span>${data ? `Base de ${data}` : "Data da base não informada"}</span>
      <span class="meta-resposta__aviso">Orientação informativa. Não substitui atendimento jurídico individual.</span>
    </div>`;
}

function htmlAcoes() {
  return `
    <div class="acoes-resposta">
      <button class="chip-acao" type="button" data-acao="possibilidades">Ver possibilidades ${icone("seta")}</button>
      <button class="chip-acao" type="button" data-acao="explicar">Explicar de outro jeito</button>
    </div>`;
}

function htmlPremissas(premissas) {
  const itens = premissas.map((premissa) => `<li>${escapar(premissa)}</li>`).join("");
  return `
    <details class="premissas">
      <summary>Premissas desta resposta</summary>
      <ul>${itens}</ul>
    </details>`;
}

function htmlEmergencia(resposta) {
  const id = `emergencia-${++sequencia}`;
  const corpo = String(resposta.resposta || "").replace(
    /^\s*Se você está em perigo agora, ligue 190[^\n]*\n+/i,
    "",
  );

  return `
    <section class="emergencia" tabindex="-1" aria-labelledby="${id}">
      <p class="emergencia__rotulo">${icone("escudo")} Risco imediato</p>
      <h3 class="emergencia__titulo" id="${id}">Se você está em perigo agora, ligue 190.</h3>

      <div class="telefones">
        <a class="telefone telefone--principal" href="tel:190">
          <span class="telefone__numero">190</span>
          <span class="telefone__nome">Polícia</span>
        </a>
        <a class="telefone telefone--verde" href="tel:180">
          <span class="telefone__numero">180</span>
          <span class="telefone__nome">Central da Mulher</span>
        </a>
        <a class="telefone" href="tel:100">
          <span class="telefone__numero">100</span>
          <span class="telefone__nome">Direitos Humanos</span>
        </a>
        <a class="telefone" href="tel:197">
          <span class="telefone__numero">197</span>
          <span class="telefone__nome">Polícia Civil</span>
        </a>
      </div>

      <div class="emergencia__corpo">${markdown(corpo)}</div>
      <p class="emergencia__rodape">A conversa não aparece em notificações nem no título da aba. Você pode continuar quando quiser.</p>
    </section>`;
}

function htmlAbstencao(resposta) {
  const motivoBruto = String(resposta.motivo_abstencao || "").trim();
  const motivoTexto = MOTIVOS_ABSTENCAO[motivoBruto] || motivoBruto;
  const motivo = motivoTexto
    ? `<p class="cartao-estado__texto">${escapar(motivoTexto)}</p>`
    : "";

  return `
    <div class="cartao-estado">
      <div class="cartao-estado__topo">
        <span class="cartao-estado__icone">${icone("info")}</span>
        <div>
          <p class="cartao-estado__titulo">Por que não respondi</p>
          ${motivo}
        </div>
      </div>
      <div class="cartao-estado__acoes">
        <button class="chip-acao" type="button" data-acao="reformular">Reformular pergunta</button>
        <a class="chip-acao" href="tel:180">${icone("telefone")}Ligar 180</a>
      </div>
    </div>`;
}

function renderResposta(resposta) {
  const artigo = document.createElement("article");
  artigo.className = "mensagem mensagem--assistente";

  const citacoes = Array.isArray(resposta.citacoes) ? resposta.citacoes : [];
  const passos = Array.isArray(resposta.proximos_passos) ? resposta.proximos_passos : [];
  const encaminhamentos = Array.isArray(resposta.encaminhamentos) ? resposta.encaminhamentos : [];
  const premissas = Array.isArray(resposta.premissas) ? resposta.premissas : [];

  let conteudo = "";

  if (resposta.emergencia) {
    conteudo += htmlEmergencia(resposta);
    if (passos.length) conteudo += htmlPassos(passos, "Passo a passo de segurança");
    if (encaminhamentos.length) conteudo += htmlAjuda(encaminhamentos);
    conteudo += htmlMeta(resposta);
  } else {
    conteudo += `<div class="bolha bolha--assistente"><span class="bolha__autor">Zelia</span>${markdown(resposta.resposta)}</div>`;

    if (resposta.abstencao) {
      conteudo += htmlAbstencao(resposta);
    } else {
      if (citacoes.length) conteudo += htmlFontes(citacoes);
      if (passos.length) conteudo += htmlPassos(passos);
      if (encaminhamentos.length) conteudo += htmlAjuda(encaminhamentos);
    }

    conteudo += htmlMeta(resposta);
    if (!resposta.abstencao) conteudo += htmlAcoes();
  }

  if (premissas.length) conteudo += htmlPremissas(premissas);

  artigo.innerHTML = `
    <div class="avatar" role="img" aria-label="Zelia">${SIMBOLO}</div>
    <div class="mensagem__conteudo">${conteudo}</div>`;

  return artigo;
}

function renderDigitando() {
  const artigo = document.createElement("article");
  artigo.className = "digitando";
  artigo.setAttribute("role", "status");
  artigo.innerHTML = `
    <div class="avatar" aria-hidden="true">${SIMBOLO}</div>
    <div class="digitando__bolha">
      <span class="pontos" aria-hidden="true"><span></span><span></span><span></span></span>
      Zelia está organizando as fontes…
    </div>`;
  return artigo;
}

function renderErro(pergunta) {
  const artigo = document.createElement("article");
  artigo.className = "mensagem mensagem--assistente";
  artigo.innerHTML = `
    <div class="avatar" role="img" aria-label="Zelia">${SIMBOLO}</div>
    <div class="mensagem__conteudo">
      <div class="cartao-estado">
        <div class="cartao-estado__topo">
          <span class="cartao-estado__icone">${icone("alerta")}</span>
          <div>
            <p class="cartao-estado__titulo">Não foi possível falar com o serviço agora.</p>
            <p class="cartao-estado__texto">Se você está em perigo, ligue 190. Você pode tentar de novo em instantes.</p>
          </div>
        </div>
        <div class="cartao-estado__acoes">
          <button class="chip-acao" type="button" data-acao="repetir" data-pergunta="${escapar(pergunta)}">Tentar de novo</button>
          <a class="chip-acao" href="tel:190">${icone("telefone")}Ligar 190</a>
        </div>
      </div>
    </div>`;
  return artigo;
}

/* --- thread -------------------------------------------------------------- */

function renderThread() {
  el.thread.innerHTML = "";
  if (!estado.mensagens.length) {
    el.thread.appendChild(noDeHtml(htmlAbertura()));
    return;
  }
  for (const mensagem of estado.mensagens) {
    el.thread.appendChild(
      mensagem.papel === "usuario"
        ? renderUsuario(mensagem.texto)
        : renderResposta(mensagem.resposta),
    );
  }
}

function rolarParaFim(forcar = false) {
  const distancia = el.thread.scrollHeight - el.thread.scrollTop - el.thread.clientHeight;
  if (forcar || distancia < 180) {
    el.thread.scrollTop = el.thread.scrollHeight;
  }
}

function estaNoFim() {
  return el.thread.scrollHeight - el.thread.scrollTop - el.thread.clientHeight < 140;
}

function revelarInicio(elemento) {
  if (!elemento) return;
  const topo = elemento.offsetTop - el.thread.offsetTop - 12;
  const maximo = el.thread.scrollHeight - el.thread.clientHeight;
  el.thread.scrollTop = Math.max(0, Math.min(topo, maximo));
}

/* --- envio --------------------------------------------------------------- */

async function respostaComAtraso(mensagem) {
  await new Promise((resolver) => window.setTimeout(resolver, 900));
  return respostaDemo(mensagem);
}

function fatosAtuais() {
  const fatos = {};
  if (estado.dataFato) fatos.data_fato = estado.dataFato;
  return fatos;
}

async function enviar(texto) {
  const limpo = String(texto || "").trim().slice(0, LIMITE_CARACTERES);
  if (!limpo || estado.ocupado) return;

  estado.ocupado = true;
  atualizarEnviar();

  estado.mensagens.push({ papel: "usuario", texto: limpo });
  el.thread.appendChild(renderUsuario(limpo));
  limparCampo();
  salvarHistorico();

  const digitando = renderDigitando();
  el.thread.appendChild(digitando);
  rolarParaFim(true);

  try {
    const resposta =
      estado.modo === "demo"
        ? await respostaComAtraso(limpo)
        : await estado.api.conversar({
            sessao: estado.sessao,
            mensagem: limpo,
            fatos: fatosAtuais(),
          });

    digitando.remove();
    estado.mensagens.push({ papel: "assistente", resposta });
    const acompanhando = estaNoFim();
    const no = renderResposta(resposta);
    el.thread.appendChild(no);
    if (acompanhando) revelarInicio(no);
    salvarHistorico();

    if (resposta.emergencia) {
      const bloco = no.querySelector(".emergencia");
      if (bloco) bloco.focus({ preventScroll: true });
      anunciar("Resposta de emergência. Se você está em perigo, ligue 190.");
    } else {
      anunciar("Nova resposta da Zelia.");
    }
  } catch {
    digitando.remove();
    const acompanhando = estaNoFim();
    const erro = renderErro(limpo);
    el.thread.appendChild(erro);
    if (acompanhando) revelarInicio(erro);
    anunciar("Não foi possível falar com o serviço. Você pode tentar de novo.");
  } finally {
    estado.ocupado = false;
    atualizarEnviar();
  }
}

/* --- composer ------------------------------------------------------------ */

function ajustarAltura() {
  el.campo.style.height = "auto";
  el.campo.style.height = `${Math.min(el.campo.scrollHeight, 160)}px`;
}

function atualizarEnviar() {
  el.enviar.disabled = !el.campo.value.trim() || estado.ocupado;
}

function limparCampo() {
  el.campo.value = "";
  el.campo.style.height = "auto";
  atualizarEnviar();
  atualizarContador();
}

function atualizarContador() {
  const total = el.campo.value.length;
  if (!el.contador) {
    el.contador = document.createElement("span");
    el.contador.className = "contador";
    el.contador.setAttribute("aria-live", "polite");
    el.composerMeta.appendChild(el.contador);
  }
  if (total > LIMITE_CARACTERES - 500) {
    el.contador.hidden = false;
    el.contador.textContent = `${total} / ${LIMITE_CARACTERES}`;
    el.contador.classList.toggle("contador--limite", total >= LIMITE_CARACTERES);
  } else {
    el.contador.hidden = true;
  }
}

/* --- privacidade --------------------------------------------------------- */

function lerPreferencias() {
  try {
    const bruto = JSON.parse(localStorage.getItem(CHAVE_PREFERENCIAS) || "{}");
    return { historico: Boolean(bruto.historico) };
  } catch {
    return { historico: false };
  }
}

function salvarPreferencias() {
  try {
    localStorage.setItem(CHAVE_PREFERENCIAS, JSON.stringify({ historico: estado.historico }));
  } catch {
    /* armazenamento indisponível: a conversa segue só em memória */
  }
}

function salvarHistorico() {
  if (!estado.historico) return;
  try {
    const dados = estado.mensagens.slice(-LIMITE_MENSAGENS);
    localStorage.setItem(CHAVE_HISTORICO, JSON.stringify(dados));
  } catch {
    /* sem espaço: ignora */
  }
}

function carregarHistorico() {
  if (!estado.historico) return;
  try {
    const bruto = JSON.parse(localStorage.getItem(CHAVE_HISTORICO) || "[]");
    if (!Array.isArray(bruto)) return;
    estado.mensagens = bruto.filter((item) => {
      if (!item || typeof item !== "object") return false;
      if (item.papel === "usuario") return typeof item.texto === "string";
      if (item.papel === "assistente") {
        return item.resposta && typeof item.resposta.resposta === "string";
      }
      return false;
    });
  } catch {
    estado.mensagens = [];
  }
}

function sincronizarPrivacidade() {
  el.switchHistorico.setAttribute("aria-checked", String(estado.historico));
  el.resumoPrivacidade.textContent = estado.historico
    ? "Histórico ligado · salvo só neste aparelho"
    : "Histórico desligado · conversa só nesta aba";
}

function alternarHistorico() {
  estado.historico = !estado.historico;
  salvarPreferencias();
  sincronizarPrivacidade();
  if (estado.historico) {
    salvarHistorico();
  } else {
    try {
      localStorage.removeItem(CHAVE_HISTORICO);
    } catch {
      /* ignora */
    }
  }
  anunciar(estado.historico ? "Histórico ligado neste aparelho." : "Histórico desligado.");
}

function apagarConversa() {
  estado.mensagens = [];
  estado.sessao = novaSessao();
  try {
    localStorage.removeItem(CHAVE_HISTORICO);
  } catch {
    /* ignora */
  }
  renderThread();
  rolarParaFim(true);
  anunciar("Conversa apagada deste aparelho.");
}

function resetarConfirmacao() {
  confirmandoExclusao = false;
  window.clearTimeout(timerConfirmacao);
  el.apagarConversa.dataset.confirmar = "false";
  el.apagarConversa.innerHTML = `${icone("lixeira")} Apagar conversa deste aparelho`;
  el.notaApagar.hidden = true;
}

function pedirConfirmacao() {
  confirmandoExclusao = true;
  el.apagarConversa.dataset.confirmar = "true";
  el.apagarConversa.innerHTML = `${icone("lixeira")} Toque de novo para confirmar`;
  el.notaApagar.hidden = false;
  timerConfirmacao = window.setTimeout(resetarConfirmacao, 7000);
}

/* --- data do fato -------------------------------------------------------- */

function definirData(iso) {
  estado.dataFato = iso && /^\d{4}-\d{2}-\d{2}$/.test(iso) ? iso : "";
  el.dataInput.value = estado.dataFato;
  el.dataDialogo.value = estado.dataFato;
  el.limparData.hidden = !estado.dataFato;
  el.chipData.dataset.definida = String(Boolean(estado.dataFato));
  el.chipDataTexto.textContent = estado.dataFato
    ? `Data do fato: ${formatarData(estado.dataFato)}`
    : "Data do fato";
  if (estado.dataFato) anunciar(`Data do fato definida em ${formatarData(estado.dataFato)}.`);
}

/* --- status e conexão ---------------------------------------------------- */

function atualizarSelo(classe, texto) {
  el.selo.className = `selo ${classe}`;
  el.seloTexto.textContent = texto;
}

function aplicarSaude(saude) {
  estado.saude = saude;
  const disponivel = saude?.status === "ok";
  const data = formatarData(saude?.data_atualizacao_base);

  atualizarSelo(
    disponivel ? "selo--ok" : "selo--degradado",
    disponivel
      ? data
        ? `Base atualizada em ${data}`
        : "Serviços disponíveis"
      : "Serviço parcialmente disponível",
  );
  el.statusTexto.textContent = disponivel
    ? "Base e busca disponíveis."
    : "Serviço parcialmente disponível. A orientação de emergência continua válida.";
  el.statusServico.className = `status ${disponivel ? "status--ok" : "status--degradado"}`;
  el.notaBase.textContent = data
    ? `Base atualizada em ${data}.`
    : "Data da base não informada.";
  el.notaBase.hidden = false;
  el.faixaDemo.hidden = true;

  el.fontesData.textContent = data || "não informada";
  el.fontesIndice.textContent = saude?.index_version || "não informado";
  el.fontesStatus.textContent = disponivel ? "disponíveis" : "parcialmente disponíveis";
}

function aplicarModoDemo(motivo = "API não conectada") {
  estado.modo = "demo";
  atualizarSelo("selo--offline", "Modo demonstração");
  el.statusTexto.textContent = "Modo demonstração. As respostas são exemplos do contrato da API.";
  el.statusServico.className = "status status--offline";
  el.notaBase.hidden = true;
  el.faixaDemo.hidden = false;
  el.fontesData.textContent = "05/11/2026 (exemplo)";
  el.fontesIndice.textContent = "não disponível";
  el.fontesStatus.textContent = "modo demonstração";
  if (motivo) console.info(`[Zelia] ${motivo}.`);
}

function aplicarSaudeDesconhecida() {
  estado.saude = null;
  atualizarSelo("selo--degradado", "Status indisponível");
  el.statusTexto.textContent = "Status dos serviços indisponível no momento.";
  el.statusServico.className = "status status--degradado";
  el.notaBase.textContent = "Data da base não informada.";
  el.notaBase.hidden = false;
  el.faixaDemo.hidden = true;

  el.fontesData.textContent = "não informada";
  el.fontesIndice.textContent = "não informado";
  el.fontesStatus.textContent = "indisponível";
}

async function conectar() {
  const params = new URLSearchParams(window.location.search);
  if (params.get("demo") === "1") {
    aplicarModoDemo("modo demonstração solicitado pela URL");
    return;
  }

  try {
    const saude = await estado.api.saude(10000);
    estado.modo = "api";
    aplicarSaude(saude);
  } catch (erro) {
    if (erro?.tipo === "rede") {
      aplicarModoDemo();
      return;
    }
    // A API respondeu (ou demorou): segue no modo real, com status incerto.
    estado.modo = "api";
    aplicarSaudeDesconhecida();
  }
}

/* --- eventos ------------------------------------------------------------- */

function abrirDialogo(dialogo) {
  if (!dialogo) return;
  if (typeof dialogo.showModal === "function") {
    dialogo.showModal();
    dialogo.focus();
  } else {
    dialogo.setAttribute("open", "");
  }
}

function fecharDialogo(dialogo) {
  if (!dialogo) return;
  if (typeof dialogo.close === "function") dialogo.close();
  else dialogo.removeAttribute("open");
}

function ligarEventos() {
  el.form.addEventListener("submit", (evento) => {
    evento.preventDefault();
    enviar(el.campo.value);
  });

  el.campo.addEventListener("input", () => {
    ajustarAltura();
    atualizarEnviar();
    atualizarContador();
  });

  el.campo.addEventListener("keydown", (evento) => {
    if (evento.key === "Enter" && !evento.shiftKey && !evento.isComposing) {
      evento.preventDefault();
      el.form.requestSubmit();
    }
  });

  el.thread.addEventListener("click", (evento) => {
    const cabecalho = evento.target.closest(".cartao__cabecalho");
    if (cabecalho) {
      const cartao = cabecalho.closest(".cartao");
      const corpo = document.getElementById(cabecalho.getAttribute("aria-controls"));
      const aberto = cartao.dataset.aberto === "true";
      cartao.dataset.aberto = String(!aberto);
      cabecalho.setAttribute("aria-expanded", String(!aberto));
      if (corpo) corpo.hidden = aberto;
      return;
    }

    const enviarExemplo = evento.target.closest("[data-enviar]");
    if (enviarExemplo) {
      enviar(enviarExemplo.dataset.enviar);
      return;
    }

    const acao = evento.target.closest("[data-acao]");
    if (!acao) return;

    const tipo = acao.dataset.acao;
    const mensagem = acao.closest(".mensagem");

    if (tipo === "possibilidades") {
      const alvo = mensagem?.querySelector(".passos");
      if (alvo) {
        alvo.scrollIntoView({ behavior: "smooth", block: "center" });
        alvo.classList.add("destaque");
        window.setTimeout(() => alvo.classList.remove("destaque"), 1400);
      }
      return;
    }

    if (tipo === "explicar") {
      enviar("Explique de forma mais simples, por favor.");
      return;
    }

    if (tipo === "reformular") {
      const ultima = [...estado.mensagens].reverse().find((item) => item.papel === "usuario");
      if (ultima) {
        el.campo.value = ultima.texto;
        ajustarAltura();
        atualizarEnviar();
      }
      el.campo.focus();
      el.campo.setSelectionRange(el.campo.value.length, el.campo.value.length);
      return;
    }

    if (tipo === "repetir") {
      enviar(acao.dataset.pergunta || "");
    }
  });

  document.addEventListener("click", (evento) => {
    const exemplo = evento.target.closest("[data-enviar]");
    if (exemplo && !evento.target.closest(".thread")) {
      enviar(exemplo.dataset.enviar);
      return;
    }
    const fechar = evento.target.closest("[data-fechar]");
    if (fechar) {
      fecharDialogo(fechar.closest("dialog"));
    }
  });

  document.querySelectorAll("dialog").forEach((dialogo) => {
    dialogo.addEventListener("click", (evento) => {
      if (evento.target !== dialogo) return;
      const caixa = dialogo.getBoundingClientRect();
      const fora =
        evento.clientX < caixa.left ||
        evento.clientX > caixa.right ||
        evento.clientY < caixa.top ||
        evento.clientY > caixa.bottom;
      if (fora) dialogo.close();
    });
  });

  el.abrirPrivacidade.addEventListener("click", () => abrirDialogo(el.dialogoPrivacidade));
  el.abrirPrivacidade2.addEventListener("click", () => abrirDialogo(el.dialogoPrivacidade));
  el.abrirFontes.addEventListener("click", () => abrirDialogo(el.dialogoFontes));
  el.abrirFontes2.addEventListener("click", () => abrirDialogo(el.dialogoFontes));

  el.switchHistorico.addEventListener("click", alternarHistorico);

  el.apagarConversa.addEventListener("click", () => {
    if (!confirmandoExclusao) {
      pedirConfirmacao();
      return;
    }
    resetarConfirmacao();
    apagarConversa();
    fecharDialogo(el.dialogoPrivacidade);
  });

  el.dataInput.addEventListener("change", () => definirData(el.dataInput.value));
  el.limparData.addEventListener("click", () => definirData(""));
  el.chipData.addEventListener("click", () => {
    el.dataDialogo.value = estado.dataFato;
    abrirDialogo(el.dialogoData);
  });
  el.dataAplicar.addEventListener("click", () => {
    definirData(el.dataDialogo.value);
    fecharDialogo(el.dialogoData);
  });
  el.dataLimpar.addEventListener("click", () => {
    definirData("");
    fecharDialogo(el.dialogoData);
  });

  el.abrirContexto.addEventListener("click", abrirContexto);
  el.fecharContexto.addEventListener("click", fecharContexto);
  el.veil.addEventListener("click", fecharContexto);

  document.addEventListener("keydown", (evento) => {
    if (evento.key === "Escape" && document.body.classList.contains("contexto-aberto")) {
      fecharContexto();
    }
  });
}

function abrirContexto() {
  document.body.classList.add("contexto-aberto");
  el.veil.hidden = false;
  el.abrirContexto.setAttribute("aria-expanded", "true");
  const foco = el.contexto.querySelector("button, input, a");
  if (foco) foco.focus();
}

function fecharContexto() {
  document.body.classList.remove("contexto-aberto");
  el.veil.hidden = true;
  el.abrirContexto.setAttribute("aria-expanded", "false");
  el.abrirContexto.focus();
}

/* --- inicialização ------------------------------------------------------- */

function novaSessao() {
  try {
    const existente = sessionStorage.getItem(CHAVE_SESSAO);
    if (existente) return existente;
    const nova =
      typeof crypto !== "undefined" && crypto.randomUUID
        ? crypto.randomUUID()
        : `s-${Date.now()}-${Math.random().toString(16).slice(2)}`;
    sessionStorage.setItem(CHAVE_SESSAO, nova);
    return nova;
  } catch {
    return `s-${Date.now()}`;
  }
}

function resolverBaseApi() {
  const params = new URLSearchParams(window.location.search);
  const porParametro = params.get("api");
  if (porParametro) return porParametro;

  const meta = document.querySelector('meta[name="zelia-api"]')?.content?.trim();
  if (meta) return meta;

  const http = window.location.protocol === "http:" || window.location.protocol === "https:";
  if (http && (window.location.pathname.startsWith("/app") || window.location.port === "8000")) {
    return window.location.origin;
  }
  return "http://localhost:8000";
}

function preencherExemplos() {
  el.exemplosLista.innerHTML = EXEMPLOS.map(
    (pergunta) => `
      <button class="exemplo-lateral" type="button" data-enviar="${escapar(pergunta)}">
        <span>${escapar(pergunta)}</span>
        ${icone("seta")}
      </button>`,
  ).join("");
}

function semearExemplo(nome) {
  const fabrica = RESPOSTAS_DEMO[nome];
  if (!fabrica) return;
  const perguntas = {
    medida: EXEMPLOS[0],
    lei: EXEMPLOS[2],
    denuncia: EXEMPLOS[1],
    emergencia: EXEMPLO_EMERGENCIA,
    abstencao: "Qual é o prazo para recurso no STJ?",
  };
  estado.modo = "demo";
  aplicarModoDemo("estado de exemplo");
  estado.mensagens = [
    { papel: "usuario", texto: perguntas[nome] },
    { papel: "assistente", resposta: fabrica() },
  ];
  renderThread();
  el.thread.scrollTop = 0;
}

function iniciar() {
  el.thread = document.getElementById("thread");
  el.form = document.getElementById("form-composer");
  el.campo = document.getElementById("campo");
  el.enviar = document.getElementById("enviar");
  el.composerMeta = document.querySelector(".composer__meta");
  el.selo = document.getElementById("selo-status");
  el.seloTexto = document.getElementById("selo-texto");
  el.statusServico = document.getElementById("status-servico");
  el.statusTexto = document.getElementById("status-texto");
  el.notaBase = document.getElementById("nota-base");
  el.faixaDemo = document.getElementById("faixa-demo");
  el.exemplosLista = document.getElementById("exemplos-lista");
  el.chipData = document.getElementById("chip-data");
  el.chipDataTexto = document.getElementById("chip-data-texto");
  el.dataInput = document.getElementById("data-fato");
  el.limparData = document.getElementById("limpar-data");
  el.dataDialogo = document.getElementById("data-dialogo");
  el.dataAplicar = document.getElementById("data-aplicar");
  el.dataLimpar = document.getElementById("data-limpar");
  el.dialogoData = document.getElementById("dialogo-data");
  el.dialogoPrivacidade = document.getElementById("dialogo-privacidade");
  el.dialogoFontes = document.getElementById("dialogo-fontes");
  el.abrirPrivacidade = document.getElementById("abrir-privacidade");
  el.abrirPrivacidade2 = document.getElementById("abrir-privacidade-2");
  el.abrirFontes = document.getElementById("abrir-fontes");
  el.abrirFontes2 = document.getElementById("abrir-fontes-2");
  el.switchHistorico = document.getElementById("switch-historico");
  el.resumoPrivacidade = document.getElementById("resumo-privacidade");
  el.apagarConversa = document.getElementById("apagar-conversa");
  el.notaApagar = document.getElementById("nota-apagar");
  el.abrirContexto = document.getElementById("abrir-contexto");
  el.fecharContexto = document.getElementById("fechar-contexto");
  el.contexto = document.getElementById("contexto");
  el.veil = document.getElementById("veil");
  el.fontesData = document.getElementById("fontes-data");
  el.fontesIndice = document.getElementById("fontes-indice");
  el.fontesStatus = document.getElementById("fontes-status");

  const preferencias = lerPreferencias();
  estado.historico = preferencias.historico;
  estado.sessao = novaSessao();
  estado.api = criarCliente(resolverBaseApi());

  preencherExemplos();
  sincronizarPrivacidade();
  definirData("");
  ligarEventos();
  atualizarEnviar();

  carregarHistorico();
  renderThread();
  if (estado.mensagens.length) rolarParaFim(true);

  const exemplo = new URLSearchParams(window.location.search).get("exemplo");
  if (exemplo) {
    semearExemplo(exemplo);
    return;
  }

  conectar();
}

iniciar();
