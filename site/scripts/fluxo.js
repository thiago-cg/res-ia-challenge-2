/* ZELIA · mapa do fluxo
 * Interface do componente: abas, reprodução de oito etapas e pulso do trilho.
 * Sem dependências. Nenhum innerHTML.
 */
(() => {
  "use strict";

  const root = document.querySelector("[data-fluxo]");
  if (!root) return;

  const lista = root.querySelector('[role="tablist"]');
  const abas = root.querySelector(".fluxo__abas");
  const tabs = lista ? Array.from(lista.querySelectorAll('[role="tab"]')) : [];
  const paineis = Array.from(root.querySelectorAll('[role="tabpanel"]'));
  if (!lista || !abas || tabs.length === 0 || tabs.length !== paineis.length) return;

  const numero = root.querySelector("[data-fluxo-numero]");
  const nome = root.querySelector("[data-fluxo-nome]");
  const progresso = root.querySelector("[data-fluxo-progresso]");
  const controle = root.querySelector("[data-fluxo-controle]");
  const rotulo = root.querySelector("[data-fluxo-rotulo]");
  const pulso = root.querySelector("[data-fluxo-pulso]");
  const movimento = root.querySelector("[data-fluxo-movimento]");
  const icones = {
    play: root.querySelector('[data-fluxo-icone="play"]'),
    pausa: root.querySelector('[data-fluxo-icone="pausa"]'),
    voltar: root.querySelector('[data-fluxo-icone="voltar"]'),
  };

  const INTERVALO = 1100;
  const total = tabs.length;
  const reduzir = window.matchMedia("(prefers-reduced-motion: reduce)");
  let atual = 0;
  let estado = "parado";
  let timer = 0;
  let frame = 0;

  function nomeDaAba(indice) {
    const alvo = tabs[indice].querySelector(".fluxo__aba-nome");
    return alvo ? alvo.textContent.trim() : "";
  }

  function posicionarPulso() {
    if (!pulso) return;
    const num = tabs[atual].querySelector(".fluxo__aba-num");
    if (!num) return;
    const caixaAbas = abas.getBoundingClientRect();
    const caixaNum = num.getBoundingClientRect();
    if (caixaNum.width === 0 && caixaNum.height === 0) return;
    abas.style.setProperty("--fluxo-pulso-x", (caixaNum.left - caixaAbas.left + caixaNum.width / 2) + "px");
    abas.style.setProperty("--fluxo-pulso-y", (caixaNum.top - caixaAbas.top + caixaNum.height / 2) + "px");
  }

  function pulsar() {
    if (!pulso || reduzir.matches) return;
    pulso.classList.remove("fluxo__pulso--pulsando");
    void pulso.offsetWidth;
    pulso.classList.add("fluxo__pulso--pulsando");
  }

  function atualizarBarra() {
    if (numero) numero.textContent = String(atual + 1);
    if (nome) nome.textContent = nomeDaAba(atual);
    if (progresso) {
      root.style.setProperty("--fluxo-progresso", (((atual + 1) / total) * 100) + "%");
    }
  }

  function atualizarControle() {
    if (!controle || !rotulo) return;
    let texto = "Percorrer o fluxo";
    let icone = "play";
    if (estado === "tocando") {
      texto = "Pausar";
      icone = "pausa";
    } else if (estado === "pausado") {
      texto = "Continuar";
    } else if (estado === "fim" || atual === total - 1) {
      texto = "Recomeçar";
      icone = "voltar";
    }
    rotulo.textContent = texto;
    Object.keys(icones).forEach((chave) => {
      const svg = icones[chave];
      if (svg) svg.hidden = chave !== icone;
    });
  }

  function atualizar() {
    tabs.forEach((tab, indice) => {
      const ativo = indice === atual;
      tab.setAttribute("aria-selected", ativo ? "true" : "false");
      tab.tabIndex = ativo ? 0 : -1;
    });
    paineis.forEach((painel, indice) => {
      const ativo = indice === atual;
      painel.hidden = !ativo;
      painel.classList.toggle("fluxo__painel--ativo", ativo);
    });
    atualizarBarra();
    atualizarControle();
    posicionarPulso();
  }

  function pararTimer() {
    if (timer) {
      window.clearInterval(timer);
      timer = 0;
    }
  }

  function finalizar() {
    pararTimer();
    estado = "fim";
    root.dataset.reproduzindo = "false";
    atualizarControle();
  }

  function agendar() {
    pararTimer();
    timer = window.setInterval(() => {
      if (atual >= total - 1) {
        finalizar();
        return;
      }
      selecionar(atual + 1, { cancelar: false });
      pulsar();
      if (atual >= total - 1) finalizar();
    }, INTERVALO);
  }

  function iniciar() {
    if (reduzir.matches) return;
    if (estado === "fim" || atual === total - 1) {
      selecionar(0, { cancelar: false });
    }
    estado = "tocando";
    root.dataset.reproduzindo = "true";
    atualizarControle();
    posicionarPulso();
    pulsar();
    agendar();
  }

  function pausar() {
    pararTimer();
    estado = "pausado";
    root.dataset.reproduzindo = "false";
    atualizarControle();
  }

  function pararPorSelecao() {
    pararTimer();
    estado = "parado";
    root.dataset.reproduzindo = "false";
    atualizarControle();
  }

  function selecionar(indice, opcoes) {
    const opcoesEfetivas = opcoes || {};
    const foco = Boolean(opcoesEfetivas.foco);
    const cancelar = opcoesEfetivas.cancelar !== false;
    const novo = Math.max(0, Math.min(total - 1, indice));
    if (cancelar) pararPorSelecao();
    atual = novo;
    atualizar();
    if (foco) tabs[atual].focus({ preventScroll: true });
  }

  function aoMudarMovimento() {
    if (!controle || !movimento) return;
    if (reduzir.matches) {
      pararTimer();
      estado = "parado";
      root.dataset.reproduzindo = "false";
      controle.hidden = true;
      movimento.hidden = false;
      atualizarControle();
    } else {
      controle.hidden = false;
      movimento.hidden = true;
      atualizarControle();
    }
  }

  lista.addEventListener("click", (evento) => {
    const tab = evento.target.closest('[role="tab"]');
    if (!tab) return;
    const indice = tabs.indexOf(tab);
    if (indice < 0) return;
    selecionar(indice);
  });

  lista.addEventListener("keydown", (evento) => {
    const tab = evento.target.closest('[role="tab"]');
    if (!tab) return;
    const indice = tabs.indexOf(tab);
    if (indice < 0) return;
    let destino = null;
    switch (evento.key) {
      case "ArrowDown":
      case "ArrowRight":
        destino = (indice + 1) % total;
        break;
      case "ArrowUp":
      case "ArrowLeft":
        destino = (indice - 1 + total) % total;
        break;
      case "Home":
        destino = 0;
        break;
      case "End":
        destino = total - 1;
        break;
      default:
        return;
    }
    evento.preventDefault();
    selecionar(destino, { foco: true });
  });

  if (controle) {
    controle.addEventListener("click", () => {
      if (estado === "tocando") {
        pausar();
      } else {
        iniciar();
      }
    });
  }

  window.addEventListener("resize", () => {
    if (frame) return;
    frame = window.requestAnimationFrame(() => {
      frame = 0;
      posicionarPulso();
    });
  }, { passive: true });

  window.addEventListener("load", posicionarPulso);

  if (document.fonts && document.fonts.ready) {
    document.fonts.ready.then(() => posicionarPulso()).catch(() => {});
  }

  if (typeof reduzir.addEventListener === "function") {
    reduzir.addEventListener("change", aoMudarMovimento);
  } else if (typeof reduzir.addListener === "function") {
    reduzir.addListener(aoMudarMovimento);
  }

  root.dataset.reproduzindo = "false";
  aoMudarMovimento();
  atualizar();
})();
