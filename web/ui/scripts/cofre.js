/**
 * Pasta segura: guarda conversas apagadas, trancadas, só neste aparelho.
 *
 * Este módulo não toca no DOM. O armazenamento é injetado (`armazem`), então roda igual em Node,
 * com um armazém em memória, e no navegador, com o IndexedDB (armazem-idb.js).
 */

import {
  ErroPin,
  abrirSelo,
  criarMeta,
  destrancar,
  selar,
  sha256Hex,
  trocarPin,
  validarPin,
} from "./cofre-cripto.js";

export { ErroPin, validarPin };

export const FALHAS_ANTES_DE_ESPERAR = 5;
const ESPERA_BASE_S = 30;
const ESPERA_MAX_S = 15 * 60;

export class ErroEspera extends Error {
  constructor(segundos) {
    super(`Muitas tentativas. Aguarde ${segundos} s.`);
    this.name = "ErroEspera";
    this.segundos = segundos;
  }
}

/** Armazém em memória: usado nos testes e como modelo da interface esperada. */
export function criarArmazemMemoria() {
  let meta = null;
  const registros = new Map();
  return {
    async lerMeta() {
      return meta ? structuredClone(meta) : null;
    },
    async gravarMeta(novo) {
      meta = structuredClone(novo);
    },
    async adicionar(registro) {
      registros.set(registro.id, structuredClone(registro));
    },
    async listar() {
      return [...registros.values()].map((r) => structuredClone(r));
    },
    async remover(id) {
      registros.delete(id);
    },
    async limparTudo() {
      meta = null;
      registros.clear();
    },
  };
}

function novoId() {
  return globalThis.crypto.randomUUID
    ? globalThis.crypto.randomUUID()
    : `r-${Date.now().toString(36)}-${Math.random().toString(36).slice(2)}`;
}

function semTrace(resposta) {
  const { trace: _ignorado, ...resto } = resposta;
  return resto;
}

/** Mensagens como serão guardadas: só campos conhecidos, com o horário. */
export function normalizarMensagens(mensagens) {
  return (Array.isArray(mensagens) ? mensagens : [])
    .filter((m) => m && (m.papel === "usuario" || m.papel === "assistente"))
    .map((m) => {
      const base = { papel: m.papel, em: typeof m.em === "string" ? m.em : null };
      return m.papel === "usuario"
        ? { ...base, texto: String(m.texto ?? "") }
        : { ...base, resposta: m.resposta ? semTrace(m.resposta) : null };
    });
}

export function criarCofre({ armazem, agora = () => new Date(), iteracoes } = {}) {
  async function existe() {
    return Boolean(await armazem.lerMeta());
  }

  async function exigirMeta() {
    const meta = await armazem.lerMeta();
    if (!meta) throw new Error("A Pasta segura ainda não foi criada.");
    return meta;
  }

  function resumo(id, registro) {
    const mensagens = registro.mensagens;
    const horarios = mensagens.map((m) => m.em).filter(Boolean).sort();
    return {
      id,
      arquivadoEm: registro.arquivadoEm,
      origem: registro.origem,
      total: mensagens.length,
      perguntas: mensagens.filter((m) => m.papel === "usuario").length,
      inicio: horarios[0] ?? null,
      fim: horarios[horarios.length - 1] ?? null,
    };
  }

  return {
    existe,

    async criar(pin) {
      const erro = validarPin(pin);
      if (erro) throw new Error(erro);
      if (await existe()) throw new Error("A Pasta segura já existe.");
      const meta = await criarMeta(pin, iteracoes ? { iteracoes } : undefined);
      await armazem.gravarMeta({ ...meta, falhas: 0, bloqueadoAte: 0 });
    },

    /** Guarda uma conversa trancada. Não precisa do PIN. Devolve o id do registro. */
    async arquivar(conversa, { origem = "apagar" } = {}) {
      const meta = await exigirMeta();
      const mensagens = normalizarMensagens(conversa?.mensagens);
      if (!mensagens.length) throw new Error("Não há conversa para guardar.");
      const id = novoId();
      const registro = {
        versao: 1,
        id,
        arquivadoEm: agora().toISOString(),
        origem,
        fuso: conversa?.fuso || Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC",
        fatos: conversa?.fatos ?? {},
        mensagens,
        hash: await sha256Hex(JSON.stringify(mensagens)),
      };
      const selo = await selar(meta.chavePublica, registro);
      await armazem.adicionar({ id, selo });
      return id;
    },

    /** Abre a pasta com o PIN. Depois de 5 erros seguidos, passa a exigir espera. */
    async desbloquear(pin) {
      const meta = await exigirMeta();
      const agoraMs = agora().getTime();
      if (meta.bloqueadoAte > agoraMs) throw new ErroEspera(Math.ceil((meta.bloqueadoAte - agoraMs) / 1000));

      let privada;
      try {
        privada = await destrancar(meta, String(pin ?? ""));
      } catch (erro) {
        if (!(erro instanceof ErroPin)) throw erro;
        const falhas = (meta.falhas || 0) + 1;
        const excesso = falhas >= FALHAS_ANTES_DE_ESPERAR ? falhas - FALHAS_ANTES_DE_ESPERAR + 1 : 0;
        const espera = excesso ? Math.min(ESPERA_MAX_S, ESPERA_BASE_S * 2 ** (excesso - 1)) : 0;
        await armazem.gravarMeta({ ...meta, falhas, bloqueadoAte: espera ? agoraMs + espera * 1000 : 0 });
        if (espera) throw new ErroEspera(espera);
        throw erro;
      }
      if (meta.falhas || meta.bloqueadoAte) await armazem.gravarMeta({ ...meta, falhas: 0, bloqueadoAte: 0 });

      let chave = privada;
      const aberta = () => {
        if (!chave) throw new Error("A Pasta segura está trancada.");
        return chave;
      };

      return {
        async listar() {
          const itens = [];
          for (const item of await armazem.listar()) {
            try {
              itens.push(resumo(item.id, await abrirSelo(aberta(), item.selo)));
            } catch (erro) {
              if (!chave) throw erro;
              itens.push({ id: item.id, danificado: true });
            }
          }
          return itens.sort((a, b) => String(b.arquivadoEm ?? "").localeCompare(String(a.arquivadoEm ?? "")));
        },
        /** Devolve o registro e se o conteúdo bate com o hash gravado. */
        async obter(id) {
          const item = (await armazem.listar()).find((r) => r.id === id);
          if (!item) throw new Error("Registro não encontrado.");
          const registro = await abrirSelo(aberta(), item.selo);
          const integro = (await sha256Hex(JSON.stringify(registro.mensagens))) === registro.hash;
          return { registro, integro };
        },
        async remover(id) {
          aberta();
          await armazem.remover(id);
        },
        async trocarPin(pinAntigo, pinNovo) {
          const erro = validarPin(pinNovo);
          if (erro) throw new Error(erro);
          const atual = await exigirMeta();
          await armazem.gravarMeta({ ...(await trocarPin(atual, pinAntigo, pinNovo)), falhas: 0, bloqueadoAte: 0 });
        },
        bloquear() {
          chave = null;
        },
        get aberta() {
          return Boolean(chave);
        },
      };
    },

    async apagarTudo() {
      await armazem.limparTudo();
    },
  };
}
