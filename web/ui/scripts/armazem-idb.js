/**
 * Armazém da Pasta segura no IndexedDB do navegador (só neste aparelho).
 * O que entra aqui já está trancado por cofre-cripto.js; este arquivo só guarda e devolve.
 */

const NOME_BANCO = "zelia-pasta-segura";
const VERSAO = 1;

function abrirBanco() {
  return new Promise((resolver, rejeitar) => {
    if (typeof indexedDB === "undefined") {
      rejeitar(new Error("IndexedDB indisponível."));
      return;
    }
    const pedido = indexedDB.open(NOME_BANCO, VERSAO);
    pedido.onupgradeneeded = () => {
      const banco = pedido.result;
      if (!banco.objectStoreNames.contains("meta")) banco.createObjectStore("meta");
      if (!banco.objectStoreNames.contains("registros")) banco.createObjectStore("registros", { keyPath: "id" });
    };
    pedido.onsuccess = () => resolver(pedido.result);
    pedido.onerror = () => rejeitar(pedido.error || new Error("Falha ao abrir o armazenamento."));
    pedido.onblocked = () => rejeitar(new Error("Armazenamento bloqueado por outra aba."));
  });
}

function pedir(banco, loja, modo, acao) {
  return new Promise((resolver, rejeitar) => {
    const transacao = banco.transaction(loja, modo);
    const resultado = acao(transacao.objectStore(loja));
    transacao.oncomplete = () => resolver(resultado?.result);
    transacao.onerror = () => rejeitar(transacao.error || new Error("Falha no armazenamento."));
    transacao.onabort = () => rejeitar(transacao.error || new Error("Operação cancelada."));
  });
}

/** Diz se dá para guardar neste navegador (alguns modos privados bloqueiam). */
export async function armazenamentoDisponivel() {
  try {
    const banco = await abrirBanco();
    banco.close();
    return true;
  } catch {
    return false;
  }
}

export function criarArmazemIdb() {
  let promessa = null;
  const banco = () => (promessa ||= abrirBanco());

  return {
    async lerMeta() {
      return (await pedir(await banco(), "meta", "readonly", (s) => s.get("cofre"))) ?? null;
    },
    async gravarMeta(meta) {
      await pedir(await banco(), "meta", "readwrite", (s) => s.put(meta, "cofre"));
    },
    async adicionar(registro) {
      await pedir(await banco(), "registros", "readwrite", (s) => s.put(registro));
    },
    async listar() {
      return (await pedir(await banco(), "registros", "readonly", (s) => s.getAll())) ?? [];
    },
    async remover(id) {
      await pedir(await banco(), "registros", "readwrite", (s) => s.delete(id));
    },
    async limparTudo() {
      const b = await banco();
      await pedir(b, "meta", "readwrite", (s) => s.clear());
      await pedir(b, "registros", "readwrite", (s) => s.clear());
    },
  };
}
