/**
 * Pasta segura: tela e fluxo.
 *
 * A pessoa guarda conversas (ao apagar, ou quando quiser) trancadas por um PIN, só neste aparelho,
 * e depois gera um relatório com dia e hora. A criptografia está em cofre-cripto.js e a lógica em
 * cofre.js; aqui fica só o que aparece na tela. Nada daqui vai para a rede.
 */

import { armazenamentoDisponivel, criarArmazemIdb } from "./armazem-idb.js";
import { ErroEspera, ErroPin, criarCofre, validarPin } from "./cofre.js";
import { formatarMomento, montarRelatorio } from "./relatorio.js";

const TEMPO_OCIOSO_MS = 5 * 60 * 1000;

function plural(n, um, varios) {
  return `${n} ${n === 1 ? um : varios}`;
}

function fabricarNo(tag, classe, texto) {
  const no = document.createElement(tag);
  if (classe) no.className = classe;
  if (texto != null) no.textContent = texto;
  return no;
}

export function criarPastaSegura({
  dialogo,
  abrirDialogo,
  fecharDialogo,
  obterConversa,
  anunciar = () => {},
  cofre = criarCofre({ armazem: criarArmazemIdb() }),
  disponivel = armazenamentoDisponivel,
}) {
  const q = (seletor) => dialogo.querySelector(seletor);
  const painel = (nome) => dialogo.querySelector(`[data-cofre="${nome}"]`);
  const campos = {
    novoPin: q("#cofre-novo-pin"),
    novoPin2: q("#cofre-novo-pin2"),
    abrirPin: q("#cofre-abrir-pin"),
  };
  const erros = {
    novo: q("#cofre-erro-novo"),
    abrir: q("#cofre-erro-abrir"),
    aberto: q("#cofre-aviso"),
  };
  const lista = q("#cofre-lista");
  const vazio = q("#cofre-vazio");
  const botaoApagarTudo = q("#cofre-apagar-tudo");

  let sessao = null;
  let timerOcioso = 0;
  let temArmazenamento = null;
  let confirmandoApagarTudo = false;
  let timerApagarTudo = 0;
  const linksTemporarios = new Set();

  /* --- estado da tela --------------------------------------------------- */

  function mostrar(nome) {
    for (const p of dialogo.querySelectorAll("[data-cofre]")) p.hidden = p.dataset.cofre !== nome;
  }

  async function existeArmazenamento() {
    if (temArmazenamento === null) temArmazenamento = await disponivel();
    return temArmazenamento;
  }

  async function situacao() {
    if (!(await existeArmazenamento())) return "indisponivel";
    return (await cofre.existe()) ? "existe" : "ausente";
  }

  async function atualizar() {
    const s = await situacao();
    if (s === "indisponivel") return mostrar("indisponivel");
    if (s === "ausente") return mostrar("novo");
    if (sessao?.aberta) {
      mostrar("aberto");
      return desenharLista();
    }
    return mostrar("trancado");
  }

  function limparSensivel() {
    for (const c of Object.values(campos)) c.value = "";
    for (const e of Object.values(erros)) {
      e.textContent = "";
      e.hidden = true;
    }
    lista.replaceChildren();
    vazio.hidden = true;
    resetarApagarTudo();
  }

  function trancar() {
    window.clearTimeout(timerOcioso);
    sessao?.bloquear();
    sessao = null;
    for (const url of linksTemporarios) URL.revokeObjectURL(url);
    linksTemporarios.clear();
    limparSensivel();
  }

  function reiniciarOcioso() {
    window.clearTimeout(timerOcioso);
    if (!sessao?.aberta) return;
    timerOcioso = window.setTimeout(async () => {
      trancar();
      await atualizar();
      anunciar("Pasta segura trancada por inatividade.");
    }, TEMPO_OCIOSO_MS);
  }

  function dizer(no, texto) {
    no.textContent = texto;
    no.hidden = !texto;
  }

  /* --- lista e relatório ------------------------------------------------ */

  function tituloDoItem(item) {
    if (item.danificado) return "Registro danificado";
    const inicio = item.inicio ? formatarMomento(item.inicio) : null;
    const fim = item.fim && item.fim !== item.inicio ? formatarMomento(item.fim) : null;
    if (inicio && fim) return `Conversa de ${inicio} a ${fim}`;
    if (inicio) return `Conversa de ${inicio}`;
    return `Conversa guardada em ${formatarMomento(item.arquivadoEm)}`;
  }

  function botaoItem(rotulo, acao, id, classe = "botao botao--secundario botao--compacto") {
    const b = fabricarNo("button", classe, rotulo);
    b.type = "button";
    b.dataset.acao = acao;
    b.dataset.id = id;
    return b;
  }

  async function desenharLista() {
    const itens = await sessao.listar();
    lista.replaceChildren();
    vazio.hidden = itens.length > 0;
    for (const item of itens) {
      const li = fabricarNo("li", "cofre__item");
      const info = fabricarNo("div", "cofre__info");
      info.append(fabricarNo("p", "cofre__titulo", tituloDoItem(item)));
      if (!item.danificado) {
        const origem = item.origem === "manual" ? "guardada por você" : "guardada ao apagar";
        info.append(
          fabricarNo(
            "p",
            "cofre__meta",
            `${plural(item.total, "mensagem", "mensagens")} · ${plural(item.perguntas, "pergunta sua", "perguntas suas")} · ${origem} em ${formatarMomento(item.arquivadoEm)}`,
          ),
        );
      }
      const acoes = fabricarNo("div", "cofre__acoes");
      if (!item.danificado) {
        acoes.append(botaoItem("Ver relatório", "ver", item.id), botaoItem("Baixar", "baixar", item.id));
      }
      acoes.append(botaoItem("Excluir", "excluir", item.id, "botao botao--secundario botao--compacto botao--destrutivo"));
      li.append(info, acoes);
      lista.append(li);
    }
  }

  async function relatorioDe(id) {
    const { registro, integro } = await sessao.obter(id);
    return montarRelatorio(registro, { integro });
  }

  function linkTemporario(conteudo, tipo) {
    const url = URL.createObjectURL(new Blob([conteudo], { type: `${tipo};charset=utf-8` }));
    linksTemporarios.add(url);
    window.setTimeout(() => {
      URL.revokeObjectURL(url);
      linksTemporarios.delete(url);
    }, 120_000);
    return url;
  }

  function baixar(nome, url) {
    const a = document.createElement("a");
    a.href = url;
    a.download = nome;
    a.rel = "noopener";
    document.body.append(a);
    a.click();
    a.remove();
  }

  async function tratarAcao(botao) {
    const { acao, id } = botao.dataset;
    reiniciarOcioso();
    dizer(erros.aberto, "");
    try {
      if (acao === "ver") {
        const r = await relatorioDe(id);
        const url = linkTemporario(r.html, "text/html");
        if (!window.open(url, "_blank", "noopener")) baixar(`${r.nome}.html`, url);
      } else if (acao === "baixar") {
        const r = await relatorioDe(id);
        baixar(`${r.nome}.html`, linkTemporario(r.html, "text/html"));
        anunciar("Relatório baixado. Guarde o arquivo em local seguro.");
      } else if (acao === "excluir") {
        if (botao.dataset.confirmar !== "true") {
          botao.dataset.confirmar = "true";
          botao.textContent = "Toque de novo para excluir";
          window.setTimeout(() => {
            if (botao.isConnected) {
              botao.dataset.confirmar = "false";
              botao.textContent = "Excluir";
            }
          }, 6000);
          return;
        }
        await sessao.remover(id);
        await desenharLista();
        anunciar("Conversa excluída da Pasta segura.");
      }
    } catch {
      dizer(erros.aberto, "Não foi possível abrir este registro.");
    }
  }

  /* --- formulários ------------------------------------------------------ */

  async function abrirComPin(pin) {
    sessao = await cofre.desbloquear(pin);
    limparSensivel();
    mostrar("aberto");
    await desenharLista();
    reiniciarOcioso();
  }

  q("#cofre-form-novo").addEventListener("submit", async (evento) => {
    evento.preventDefault();
    dizer(erros.novo, "");
    const pin = campos.novoPin.value;
    const erro = validarPin(pin);
    if (erro) return dizer(erros.novo, erro);
    if (pin !== campos.novoPin2.value) return dizer(erros.novo, "Os dois PINs não são iguais.");
    try {
      await cofre.criar(pin);
      await abrirComPin(pin);
      anunciar("Pasta segura criada.");
    } catch {
      dizer(erros.novo, "Não foi possível criar a Pasta segura neste navegador.");
    }
  });

  q("#cofre-form-abrir").addEventListener("submit", async (evento) => {
    evento.preventDefault();
    dizer(erros.abrir, "");
    const botao = q("#cofre-form-abrir button[type=submit]");
    botao.disabled = true;
    try {
      await abrirComPin(campos.abrirPin.value);
    } catch (erro) {
      campos.abrirPin.value = "";
      if (erro instanceof ErroEspera) dizer(erros.abrir, `Muitas tentativas. Tente de novo em ${erro.segundos} s.`);
      else if (erro instanceof ErroPin) dizer(erros.abrir, "PIN incorreto.");
      else dizer(erros.abrir, "Não foi possível abrir a Pasta segura.");
    } finally {
      botao.disabled = false;
    }
  });

  q("#cofre-bloquear").addEventListener("click", async () => {
    trancar();
    await atualizar();
    campos.abrirPin.focus();
    anunciar("Pasta segura trancada.");
  });

  q("#cofre-guardar-atual").addEventListener("click", async () => {
    reiniciarOcioso();
    dizer(erros.aberto, "");
    const conversa = obterConversa();
    if (!conversa?.mensagens?.length) return dizer(erros.aberto, "Ainda não há conversa para guardar.");
    try {
      await cofre.arquivar(conversa, { origem: "manual" });
      await desenharLista();
      anunciar("Conversa guardada na Pasta segura.");
    } catch {
      dizer(erros.aberto, "Não foi possível guardar a conversa.");
    }
  });

  lista.addEventListener("click", (evento) => {
    const botao = evento.target.closest("button[data-acao]");
    if (botao) tratarAcao(botao);
  });

  function resetarApagarTudo() {
    confirmandoApagarTudo = false;
    window.clearTimeout(timerApagarTudo);
    botaoApagarTudo.dataset.confirmar = "false";
    botaoApagarTudo.textContent = "Apagar a Pasta segura";
  }

  botaoApagarTudo.addEventListener("click", async () => {
    reiniciarOcioso();
    if (!confirmandoApagarTudo) {
      confirmandoApagarTudo = true;
      botaoApagarTudo.dataset.confirmar = "true";
      botaoApagarTudo.textContent = "Toque de novo: apaga tudo, sem volta";
      timerApagarTudo = window.setTimeout(resetarApagarTudo, 7000);
      return;
    }
    resetarApagarTudo();
    try {
      await cofre.apagarTudo();
      trancar();
      await atualizar();
      anunciar("Pasta segura apagada.");
    } catch {
      dizer(erros.aberto, "Não foi possível apagar a Pasta segura.");
    }
  });

  dialogo.addEventListener("pointerdown", reiniciarOcioso);
  dialogo.addEventListener("keydown", reiniciarOcioso);
  dialogo.addEventListener("close", trancar);

  /* --- o que o resto do app usa ---------------------------------------- */

  return {
    situacao,

    async abrir() {
      trancar();
      abrirDialogo(dialogo);
      await atualizar();
      const primeiro = dialogo.querySelector("[data-cofre]:not([hidden]) input");
      primeiro?.focus();
    },

    /** Guarda a conversa trancada, sem pedir o PIN. Lança se não conseguir. */
    async arquivarConversa(conversa, origem = "apagar") {
      return cofre.arquivar(conversa, { origem });
    },

    fechar() {
      fecharDialogo(dialogo);
    },
  };
}
