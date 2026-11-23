import { criarCliente } from "./api.js";

const api = criarCliente(window.location.origin);

const telaLogin = document.getElementById("tela-login");
const telaPainel = document.getElementById("tela-painel");
const formLogin = document.getElementById("form-login");
const botaoSair = document.getElementById("botao-sair");
const botaoAtualizar = document.getElementById("botao-atualizar");
const filtroStatus = document.getElementById("filtro-status");
const lista = document.getElementById("lista-solicitacoes");
const mensagem = document.getElementById("mensagem");

function avisar(texto) {
  mensagem.textContent = texto;
}

function mostrarPainel(autenticado) {
  telaLogin.hidden = autenticado;
  telaPainel.hidden = !autenticado;
  botaoSair.hidden = !autenticado;
}

function formatarData(data) {
  return new Date(data).toLocaleString("pt-BR");
}

function criarCartao(solicitacao) {
  const cartao = document.createElement("article");
  cartao.className = "policia__solicitacao";

  const titulo = document.createElement("h3");
  titulo.textContent = `Solicitação ${solicitacao.id}`;

  const status = document.createElement("span");
  status.className = "policia__status";
  status.textContent =
    solicitacao.status === "pending" ? "Pendente" : "Respondida";

  const data = document.createElement("p");
  data.textContent = `Recebida em ${formatarData(solicitacao.created_at)}`;

  const texto = document.createElement("p");
  texto.textContent = solicitacao.message;

  cartao.append(titulo, status, data, texto);

  if (solicitacao.status === "responded") {
    const resposta = document.createElement("p");
    resposta.textContent = `Resposta: ${solicitacao.response}`;
    cartao.append(resposta);
  } else {
    const formulario = document.createElement("form");
    const campo = document.createElement("textarea");
    campo.required = true;
    campo.maxLength = 4000;
    campo.placeholder = "Escreva a resposta à solicitação...";
    campo.setAttribute("aria-label", "Resposta à solicitação");

    const botao = document.createElement("button");
    botao.className = "botao botao--primario";
    botao.type = "submit";
    botao.textContent = "Enviar resposta";

    formulario.append(campo, botao);
    formulario.addEventListener("submit", async (evento) => {
      evento.preventDefault();
      botao.disabled = true;

      try {
        await api.responderSolicitacao(solicitacao.id, campo.value.trim());
        avisar("Resposta registrada com sucesso.");
        await carregarSolicitacoes();
      } catch {
        avisar("Não foi possível enviar a resposta. Verifique sua sessão.");
        botao.disabled = false;
      }
    });

    cartao.append(formulario);
  }

  return cartao;
}

async function carregarSolicitacoes() {
  lista.replaceChildren();
  const carregando = document.createElement("p");
  carregando.textContent = "Carregando solicitações...";
  lista.append(carregando);

  try {
    const solicitacoes = await api.listarSolicitacoes(filtroStatus.value);
    lista.replaceChildren();

    if (!solicitacoes.length) {
      const vazio = document.createElement("p");
      vazio.textContent = "Nenhuma solicitação encontrada.";
      lista.append(vazio);
      return;
    }

    solicitacoes.forEach((solicitacao) => {
      lista.append(criarCartao(solicitacao));
    });
  } catch (erro) {
    lista.replaceChildren();
    avisar(
      erro.status === 401
        ? "Sua sessão expirou. Entre novamente."
        : "Não foi possível carregar as solicitações.",
    );
    mostrarPainel(false);
  }
}

formLogin.addEventListener("submit", async (evento) => {
  evento.preventDefault();
  const dados = new FormData(formLogin);
  const usuario = String(dados.get("username")).trim();
  const senha = String(dados.get("password"));

  try {
    await api.loginPolicia(usuario, senha);
    formLogin.reset();
    avisar("Login realizado com sucesso.");
    mostrarPainel(true);
    await carregarSolicitacoes();
  } catch {
    avisar("Não foi possível entrar. Confira usuário e senha.");
  }
});

botaoAtualizar.addEventListener("click", carregarSolicitacoes);
filtroStatus.addEventListener("change", carregarSolicitacoes);

botaoSair.addEventListener("click", async () => {
  try {
    await api.logoutPolicia();
  } finally {
    mostrarPainel(false);
    lista.replaceChildren();
    avisar("Você saiu do painel.");
  }
});

mostrarPainel(false);
