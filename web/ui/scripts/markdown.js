/**
 * Markdown mínimo e seguro.
 * O texto vem da API e é sempre tratado como dado: primeiro escapa, depois
 * aplica um conjunto pequeno de marcações (parágrafos, listas, negrito,
 * itálico e código). Nenhum HTML bruto passa.
 */

const ESCAPES = {
  "&": "&amp;",
  "<": "&lt;",
  ">": "&gt;",
  '"': "&quot;",
  "'": "&#39;",
};

export function escapar(valor) {
  return String(valor ?? "").replace(/[&<>"']/g, (caractere) => ESCAPES[caractere]);
}

function inline(texto) {
  return texto
    .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
    .replace(/(^|[\s(])\*(?!\s)([^*]+?)\*(?=[\s).,;:!?]|$)/g, "$1<em>$2</em>")
    .replace(/`([^`]+)`/g, "<code>$1</code>")
    .replace(/\n/g, "<br>");
}

export function markdown(texto) {
  const bruto = String(texto ?? "").replace(/\r\n/g, "\n").trim();
  if (!bruto) return "";

  const linhas = escapar(bruto).split("\n");
  const partes = [];
  let paragrafo = [];
  let lista = null;

  const fecharLista = () => {
    if (lista) {
      partes.push(`</${lista}>`);
      lista = null;
    }
  };

  const despejarParagrafo = () => {
    if (paragrafo.length) {
      // Linhas que terminam sem pontuação final são quebras de composição do
      // texto de origem, não do conteúdo: junta com espaço em vez de <br>.
      let texto = "";
      for (const linha of paragrafo) {
        if (!texto) {
          texto = linha;
          continue;
        }
        texto += /[.!?:;]$/.test(texto) ? "\n" : " ";
        texto += linha;
      }
      partes.push(`<p>${inline(texto)}</p>`);
      paragrafo = [];
    }
  };

  for (const linha of linhas) {
    const limpa = linha.trim();

    if (!limpa) {
      despejarParagrafo();
      fecharLista();
      continue;
    }

    const itemNaoOrdenado = limpa.match(/^[-•*]\s+(.*)$/);
    if (itemNaoOrdenado) {
      despejarParagrafo();
      if (lista !== "ul") {
        fecharLista();
        partes.push("<ul>");
        lista = "ul";
      }
      partes.push(`<li>${inline(itemNaoOrdenado[1])}</li>`);
      continue;
    }

    const itemOrdenado = limpa.match(/^\d+[.)]\s+(.*)$/);
    if (itemOrdenado) {
      despejarParagrafo();
      if (lista !== "ol") {
        fecharLista();
        partes.push("<ol>");
        lista = "ol";
      }
      partes.push(`<li>${inline(itemOrdenado[1])}</li>`);
      continue;
    }

    fecharLista();
    paragrafo.push(limpa);
  }

  despejarParagrafo();
  fecharLista();
  return partes.join("");
}
