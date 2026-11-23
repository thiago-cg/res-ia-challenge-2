/**
 * Cliente HTTP da API do projeto.
 * Mesmo contrato usado pelo Streamlit: POST /chat e GET /health.
 */

export class ErroApi extends Error {
  constructor(mensagem, { status = 0, tipo = "rede" } = {}) {
    super(mensagem);
    this.name = "ErroApi";
    this.status = status;
    this.tipo = tipo;
  }
}

async function comTempoLimite(url, opcoes, tempoLimite) {
  const controlador = new AbortController();
  const timer = setTimeout(() => controlador.abort(), tempoLimite);
  try {
    return await fetch(url, { ...opcoes, signal: controlador.signal });
  } catch (erro) {
    if (erro?.name === "AbortError") {
      throw new ErroApi("Tempo esgotado ao falar com o serviço.", { tipo: "tempo" });
    }
    throw new ErroApi("Não foi possível alcançar o serviço.", { tipo: "rede" });
  } finally {
    clearTimeout(timer);
  }
}

export function criarCliente(base) {
  const raiz = String(base || "").replace(/\/+$/, "");

  async function requisicao(caminho, opcoes = {}, tempoLimite = 15000) {
    const resposta = await comTempoLimite(
      `${raiz}/api/v1${caminho}`,
      {
        ...opcoes,
        credentials: "same-origin",
        headers: {
          Accept: "application/json",
          ...(opcoes.headers || {}),
        },
      },
      tempoLimite,
    );

    if (!resposta.ok) {
      throw new ErroApi("Não foi possível concluir a operação.", {
        status: resposta.status,
        tipo: "http",
      });
    }

    return resposta.json();
  }

  return {
    base: raiz,

    async saude(tempoLimite = 2500) {
      const resposta = await comTempoLimite(
        `${raiz}/health`,
        { headers: { Accept: "application/json" } },
        tempoLimite,
      );
      if (!resposta.ok) {
        throw new ErroApi("Serviço indisponível.", {
          status: resposta.status,
          tipo: "http",
        });
      }
      return resposta.json();
    },

    async conversar({ sessao, mensagem, fatos, tempoLimite = 60000 }) {
      const corpo = { session_id: sessao, message: mensagem };
      if (fatos && Object.keys(fatos).length) corpo.facts = fatos;

      const resposta = await comTempoLimite(
        `${raiz}/chat`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json", Accept: "application/json" },
          body: JSON.stringify(corpo),
        },
        tempoLimite,
      );

      if (!resposta.ok) {
        throw new ErroApi("O serviço respondeu com erro.", {
          status: resposta.status,
          tipo: "http",
        });
      }

      return resposta.json();
    },

    /**
     * Delegacias mais próximas. POST (e não GET) para que a localização nunca
     * apareça em query string, histórico ou log de acesso. A localização não é
     * guardada aqui: sai da função junto com a resposta.
     */
    async servicosProximos(corpo, tempoLimite = 15000) {
      const resposta = await comTempoLimite(
        `${raiz}/services/nearby`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json", Accept: "application/json" },
          body: JSON.stringify(corpo),
        },
        tempoLimite,
      );

      if (!resposta.ok) {
        throw new ErroApi("Não foi possível consultar as delegacias.", {
          status: resposta.status,
          tipo: "http",
        });
      }

      return resposta.json();
    },

    async solicitarContato(message) {
      return requisicao("/contact-requests", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message }),
      });
    },

    async consultarSolicitacao(id) {
      return requisicao(`/contact-requests/${encodeURIComponent(id)}`);
    },

    async loginPolicia(username, password) {
      return requisicao("/police/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ username, password }),
      });
    },

    async logoutPolicia() {
      return requisicao("/police/logout", { method: "POST" });
    },

    async listarSolicitacoes(status) {
      const filtro = status
        ? `?status=${encodeURIComponent(status)}`
        : "";
      return requisicao(`/police/contact-requests${filtro}`);
    },

    async responderSolicitacao(id, response) {
      return requisicao(
        `/police/contact-requests/${encodeURIComponent(id)}/response`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ response }),
        },
      );
    },
  };
}

/**
 * Métodos do Canal Mulher–Polícia.
 * O cookie de autenticação policial é enviado pelo navegador.
 */
