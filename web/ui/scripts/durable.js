/**
 * Cliente do fluxo durável (T11).
 *
 * A promessa nova: a pessoa pode fechar a aba. O envio aceita um trabalho no servidor e a
 * interface acompanha por revisão; se a aba morrer no meio, a próxima abertura retoma a conversa
 * e o resultado aparece sem reenviar nada.
 *
 * Este módulo não toca no DOM: ele só fala com a API. Assim pode ser testado em Node, com fetch
 * falso, provando idempotência e retomada sem precisar de navegador.
 */

export const COOKIE_CONVERSA = "zelia_owner";

/** Identificador do envio, estável entre retries (INV05). */
export function novoIdMensagem(gerador) {
  if (typeof gerador === "function") return gerador();
  if (globalThis.crypto?.randomUUID) return globalThis.crypto.randomUUID();
  return "m-" + Date.now().toString(36) + "-" + Math.random().toString(36).slice(2);
}

export class ErroDuravel extends Error {
  constructor(mensagem, { status = 0, tipo = "rede", runId = null } = {}) {
    super(mensagem);
    this.name = "ErroDuravel";
    this.status = status;
    this.tipo = tipo;
    this.runId = runId;
  }
}

async function lerJson(resposta) {
  try {
    return await resposta.json();
  } catch {
    return null;
  }
}

export function criarClienteDuravel(base, { fetchImpl, espera } = {}) {
  const raiz = String(base || "").replace(/\/+$/, "");
  const buscar = fetchImpl || ((...args) => globalThis.fetch(...args));
  const dormir = espera || ((ms) => new Promise((r) => setTimeout(r, ms)));

  async function requisitar(caminho, opcoes = {}) {
    const resposta = await buscar(raiz + caminho, {
      credentials: "same-origin",
      headers: { Accept: "application/json", ...(opcoes.headers || {}) },
      ...opcoes,
    });
    return resposta;
  }

  return {
    base: raiz,

    /** Conversa atual do cookie, ou null quando não existe/expirada. */
    async conversaAtual() {
      const resposta = await requisitar("/api/v1/conversations/current", { method: "GET" });
      if (resposta.status === 401 || resposta.status === 404) return null;
      if (!resposta.ok) throw new ErroDuravel("Falha ao consultar a conversa.", { status: resposta.status, tipo: "http" });
      return lerJson(resposta);
    },

    async criarConversa() {
      const resposta = await requisitar("/api/v1/conversations", { method: "POST" });
      if (!resposta.ok) throw new ErroDuravel("Falha ao abrir a conversa.", { status: resposta.status, tipo: "http" });
      return lerJson(resposta);
    },

    /**
     * Envia ou confirma um envio. Devolve { runId, repetido }.
     * Repetir com o mesmo clientMessageId devolve a MESMA execução (200 em vez de 202).
     */
    async enviar(conversationId, { mensagem, clientMessageId }) {
      const id = clientMessageId || novoIdMensagem();
      let resposta;
      try {
        resposta = await requisitar("/api/v1/conversations/" + conversationId + "/messages", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ message: mensagem, client_message_id: id }),
        });
      } catch (erro) {
        // Não sabemos se o servidor recebeu: a interface deve oferecer verificar, nunca reenviar
        // com id novo (isso duplicaria a mensagem).
        throw new ErroDuravel("Não foi possível confirmar o envio.", { tipo: "rede" });
      }

      if (resposta.status === 409) {
        const corpo = (await lerJson(resposta)) || {};
        throw new ErroDuravel("Já existe uma execução em andamento.", {
          status: 409,
          tipo: "conflito",
          runId: corpo.run_id || null,
        });
      }
      if (!resposta.ok) {
        throw new ErroDuravel("O serviço recusou a mensagem.", { status: resposta.status, tipo: "http" });
      }
      const corpo = (await lerJson(resposta)) || {};
      return { runId: corpo.run_id, repetido: resposta.status === 200, clientMessageId: id };
    },

    async estado(conversationId, runId, since) {
      const sufixo = since == null ? "" : "?since=" + since;
      const resposta = await requisitar(
        "/api/v1/conversations/" + conversationId + "/runs/" + runId + sufixo,
        { method: "GET" },
      );
      if (resposta.status === 304) return { mudou: false, revision: since };
      if (!resposta.ok) throw new ErroDuravel("Falha ao acompanhar a execução.", { status: resposta.status, tipo: "http" });
      const corpo = (await lerJson(resposta)) || {};
      return { mudou: true, ...corpo };
    },

    async resultado(conversationId, runId) {
      const resposta = await requisitar(
        "/api/v1/conversations/" + conversationId + "/runs/" + runId + "/result",
        { method: "GET" },
      );
      if (resposta.status === 409) return null;
      if (!resposta.ok) throw new ErroDuravel("Falha ao recuperar o resultado.", { status: resposta.status, tipo: "http" });
      return lerJson(resposta);
    },

    /** Espera o run terminar e devolve o ChatResponse publicado. */
    async aguardar(conversationId, runId, { intervalo = 1000, maxTentativas = 120 } = {}) {
      let revisao = null;
      let status = null;
      for (let tentativa = 0; tentativa < maxTentativas; tentativa += 1) {
        const estado = await this.estado(conversationId, runId, revisao);
        // 304 não traz corpo: o status continua o último conhecido, senão o laço perderia o
        // estado a cada "nada mudou" e nunca reconheceria o fim.
        if (estado.mudou) {
          revisao = estado.revision;
          status = estado.status;
        }

        if (status === "succeeded") {
          const publicado = await this.resultado(conversationId, runId);
          if (publicado) return publicado;
        }
        if (["failed", "cancelled", "expired"].includes(status)) {
          throw new ErroDuravel("A execução terminou sem resposta.", { tipo: status });
        }
        await dormir(intervalo);
      }
      throw new ErroDuravel("Tempo esgotado aguardando a resposta.", { tipo: "tempo" });
    },
  };
}
