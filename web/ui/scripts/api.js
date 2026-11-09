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
  };
}
