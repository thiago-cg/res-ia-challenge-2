/**
 * Relatório de uma conversa guardada na Pasta segura.
 *
 * Gera um documento HTML autônomo (abre em qualquer navegador, imprime e salva em PDF) e uma
 * versão em texto. Cada mensagem leva dia e hora; o fim traz o código de integridade (SHA-256) do
 * conteúdo guardado. Tudo que vem da conversa é escapado: o relatório nunca executa o que a
 * pessoa ou a resposta escreveram.
 *
 * Não promete valor jurídico: é o registro da própria pessoa. Quem orienta como usá-lo é a
 * delegacia, a Defensoria ou um advogado.
 */

export const AVISO_RELATORIO =
  "Este é um registro pessoal, feito a partir da conversa guardada neste aparelho. Ele mostra o que foi " +
  "perguntado e respondido, com dia e hora. Não substitui orientação jurídica nem prova, por si só, o que " +
  "aconteceu. Leve-o à delegacia, à Defensoria Pública ou a um advogado, que dirão como usá-lo.";

export function escaparHtml(texto) {
  return String(texto ?? "").replace(/[&<>"']/g, (c) => `&#${c.charCodeAt(0)};`);
}

export function formatarMomento(iso, fuso) {
  if (!iso) return "horário não registrado";
  const data = new Date(iso);
  if (Number.isNaN(data.getTime())) return "horário não registrado";
  const opcoes = { timeZone: fuso || undefined };
  try {
    const dia = data.toLocaleDateString("pt-BR", { ...opcoes, day: "2-digit", month: "2-digit", year: "numeric" });
    const hora = data.toLocaleTimeString("pt-BR", { ...opcoes, hour: "2-digit", minute: "2-digit", second: "2-digit" });
    return `${dia} às ${hora}`;
  } catch {
    return `${data.toLocaleDateString("pt-BR")} às ${data.toLocaleTimeString("pt-BR")}`;
  }
}

function linhasDaResposta(resposta) {
  const r = resposta || {};
  const linhas = [];
  linhas.push({ tipo: "texto", valor: String(r.resposta ?? "") });
  const citacoes = Array.isArray(r.citacoes) ? r.citacoes : [];
  if (citacoes.length) {
    linhas.push({
      tipo: "lista",
      titulo: "Fontes citadas",
      itens: citacoes.map((c) => [c.citacao, c.fonte_url].filter(Boolean).join(" · ")),
    });
  }
  const passos = Array.isArray(r.proximos_passos) ? r.proximos_passos : [];
  if (passos.length) linhas.push({ tipo: "lista", titulo: "Próximos passos sugeridos", itens: passos.map(String) });
  const ajuda = Array.isArray(r.encaminhamentos) ? r.encaminhamentos : [];
  if (ajuda.length) {
    linhas.push({
      tipo: "lista",
      titulo: "Encaminhamentos",
      itens: ajuda.map((e) => [e.nome || e.titulo, e.telefone, e.descricao].filter(Boolean).join(" · ")),
    });
  }
  if (r.nivel_confianca) linhas.push({ tipo: "nota", valor: `Nível de confiança: ${r.nivel_confianca}` });
  if (r.emergencia) linhas.push({ tipo: "nota", valor: "Resposta de emergência: em perigo, ligue 190." });
  if (r.data_atualizacao_base) linhas.push({ tipo: "nota", valor: `Base atualizada em ${r.data_atualizacao_base}` });
  return linhas;
}

function paraTexto(texto) {
  return String(texto ?? "").replace(/\r\n/g, "\n");
}

function nomeArquivo(registro) {
  const base = String(registro.arquivadoEm || "").slice(0, 16).replace(/[^0-9]/g, "") || "registro";
  return `zelia-registro-${base}`;
}

export function montarRelatorio(registro, { integro = true, geradoEm = new Date() } = {}) {
  const fuso = registro.fuso || "UTC";
  const mensagens = registro.mensagens || [];
  const horarios = mensagens.map((m) => m.em).filter(Boolean).sort();
  const periodo = horarios.length
    ? horarios[0] === horarios[horarios.length - 1]
      ? formatarMomento(horarios[0], fuso)
      : `${formatarMomento(horarios[0], fuso)} a ${formatarMomento(horarios[horarios.length - 1], fuso)}`
    : "horários não registrados";
  const gerado = formatarMomento(geradoEm.toISOString(), fuso);
  const guardado = formatarMomento(registro.arquivadoEm, fuso);
  const dataFato = registro.fatos?.data_fato ? registro.fatos.data_fato.split("-").reverse().join("/") : "";

  // --- texto simples
  const t = [];
  t.push("REGISTRO DE CONVERSA · ZELIA", "");
  t.push(`Período da conversa: ${periodo} (fuso ${fuso})`);
  t.push(`Guardada em: ${guardado}`);
  if (dataFato) t.push(`Data do fato informada: ${dataFato}`);
  t.push(`Mensagens: ${mensagens.length}`, "");
  mensagens.forEach((m, i) => {
    const autor = m.papel === "usuario" ? "Você" : "Zelia";
    t.push(`[${i + 1}] ${autor} · ${formatarMomento(m.em, fuso)}`);
    if (m.papel === "usuario") t.push(paraTexto(m.texto));
    else {
      for (const linha of linhasDaResposta(m.resposta)) {
        if (linha.tipo === "texto") t.push(paraTexto(linha.valor));
        else if (linha.tipo === "lista") t.push(`${linha.titulo}:`, ...linha.itens.map((i2) => `  - ${i2}`));
        else t.push(linha.valor);
      }
    }
    t.push("");
  });
  t.push(`Código de integridade (SHA-256): ${registro.hash}`);
  t.push(integro ? "Integridade: o conteúdo confere com o código." : "ATENÇÃO: o conteúdo NÃO confere com o código.");
  t.push(`Relatório gerado em ${gerado}.`, "", AVISO_RELATORIO);

  // --- HTML
  const corpo = mensagens
    .map((m, i) => {
      const autor = m.papel === "usuario" ? "Você" : "Zelia";
      const cab = `<header><span class="n">${i + 1}</span> <strong>${escaparHtml(autor)}</strong> <time>${escaparHtml(
        formatarMomento(m.em, fuso),
      )}</time></header>`;
      let conteudo = "";
      if (m.papel === "usuario") conteudo = `<p>${escaparHtml(paraTexto(m.texto)).replace(/\n/g, "<br>")}</p>`;
      else {
        for (const linha of linhasDaResposta(m.resposta)) {
          if (linha.tipo === "texto") conteudo += `<p>${escaparHtml(paraTexto(linha.valor)).replace(/\n/g, "<br>")}</p>`;
          else if (linha.tipo === "lista")
            conteudo += `<h3>${escaparHtml(linha.titulo)}</h3><ul>${linha.itens
              .map((i2) => `<li>${escaparHtml(i2)}</li>`)
              .join("")}</ul>`;
          else conteudo += `<p class="nota">${escaparHtml(linha.valor)}</p>`;
        }
      }
      return `<section class="msg msg--${m.papel === "usuario" ? "voce" : "zelia"}">${cab}${conteudo}</section>`;
    })
    .join("\n");

  const html = `<!doctype html>
<html lang="pt-BR">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex,nofollow">
<title>Registro de conversa · Zelia</title>
<style>
  body{font:16px/1.55 system-ui,-apple-system,"Segoe UI",sans-serif;color:#1e2a3a;max-width:760px;margin:0 auto;padding:32px 20px;background:#fff}
  h1{font-size:24px;margin:0 0 4px} h3{font-size:14px;margin:12px 0 4px}
  .meta{color:#4b5a6c;font-size:14px;margin:0 0 24px} .meta p{margin:2px 0}
  .msg{border:1px solid #d9dee5;border-radius:12px;padding:12px 16px;margin:0 0 12px;break-inside:avoid}
  .msg--voce{background:#f1f4fb} header{display:flex;gap:8px;align-items:baseline;font-size:14px;margin-bottom:6px}
  header time{color:#4b5a6c;margin-left:auto;font-variant-numeric:tabular-nums} .n{color:#4b5a6c}
  p{margin:6px 0} ul{margin:4px 0 4px 18px;padding:0} .nota{font-size:13px;color:#4b5a6c}
  .fim{margin-top:24px;border-top:2px solid #1e2a3a;padding-top:12px;font-size:13px}
  .hash{font-family:ui-monospace,Menlo,monospace;word-break:break-all}
  .alerta{color:#8f1d17;font-weight:600}
  button{font:inherit;padding:8px 16px;border-radius:999px;border:1px solid #1e2a3a;background:#fff;cursor:pointer;margin-bottom:16px}
  @media print{button{display:none} body{padding:0}}
</style>
</head>
<body>
<button type="button" onclick="window.print()">Imprimir ou salvar em PDF</button>
<h1>Registro de conversa · Zelia</h1>
<div class="meta">
<p>Período da conversa: <strong>${escaparHtml(periodo)}</strong> (fuso ${escaparHtml(fuso)})</p>
<p>Guardada em: ${escaparHtml(guardado)}</p>
${dataFato ? `<p>Data do fato informada: ${escaparHtml(dataFato)}</p>` : ""}
<p>Mensagens: ${mensagens.length}</p>
</div>
${corpo}
<div class="fim">
<p>Código de integridade (SHA-256): <span class="hash">${escaparHtml(registro.hash)}</span></p>
<p class="${integro ? "" : "alerta"}">${
    integro ? "O conteúdo confere com o código." : "ATENÇÃO: o conteúdo NÃO confere com o código."
  }</p>
<p>Relatório gerado em ${escaparHtml(gerado)}.</p>
<p>${escaparHtml(AVISO_RELATORIO)}</p>
</div>
</body>
</html>`;

  return { html, texto: t.join("\n"), nome: nomeArquivo(registro) };
}
