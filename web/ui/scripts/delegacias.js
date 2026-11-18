/**
 * ZELIA · delegacias mais próximas
 *
 * Painel (diálogo) que consulta POST /services/nearby e mostra o resultado como
 * cartões e um esquema de distância e direção desenhado em SVG, no próprio
 * navegador. Não há mapa de ruas de propósito: tiles de mapa (OpenStreetMap,
 * Google) revelariam a região consultada e o IP a terceiros, e a interface
 * promete não falar com ninguém além da API da Zelia.
 *
 * Privacidade da localização:
 *  - só é pedida quando a usuária toca em "Usar minha localização";
 *  - nunca vai para localStorage, sessionStorage, URL ou histórico da conversa;
 *  - é arredondada a ~110 m antes de sair do navegador;
 *  - o resultado fica só em memória e é apagado ao fechar o painel.
 * O único link que sai do app é o "Como chegar", aberto por toque, e leva só o
 * destino (nunca a posição da usuária).
 */

import { escapar } from "./markdown.js";

const ROTULOS_TIPO = {
  deam: "Delegacia da Mulher (DEAM)",
  nucleo_atendimento_mulher: "Núcleo de Atendimento à Mulher",
  delegacia_comum: "Delegacia de Polícia",
};

const UFS = [
  "AC", "AL", "AP", "AM", "BA", "CE", "DF", "ES", "GO", "MA", "MT", "MS", "MG", "PA",
  "PB", "PR", "PE", "PI", "RJ", "RN", "RS", "RO", "RR", "SC", "SP", "SE", "TO",
];

const PONTOS_CARDEAIS = [
  "ao norte", "ao nordeste", "a leste", "ao sudeste",
  "ao sul", "ao sudoeste", "a oeste", "ao noroeste",
];

const PASSOS_ANEL_KM = [1, 2, 5, 10, 25, 50, 100, 250, 500, 1000, 2500];
const LIMITE_RESULTADOS = 5;
const SAIDA_RAPIDA_URL = "https://www.google.com.br/";

/* --- funções puras (testáveis sem DOM) ------------------------------------ */

/** Arredonda para 3 casas (~110 m): suficiente para achar a delegacia, pouco para rastrear. */
export function arredondarCoordenada(valor) {
  return Math.round(Number(valor) * 1000) / 1000;
}

export function formatarDistancia(km) {
  if (km === null || km === undefined || Number.isNaN(Number(km))) return "";
  const n = Number(km);
  if (n < 1) return `${Math.max(1, Math.round(n * 10) * 100)} m`;
  return `${n.toLocaleString("pt-BR", { maximumFractionDigits: n < 10 ? 1 : 0 })} km`;
}

/** Coordenada aproximada (centro da região) não sustenta distância em metros. */
export function rotuloDistancia(servico) {
  const km = Number(servico.distancia_km);
  if (!servico.coordenada_verificada && km < 1) return "na região";
  return formatarDistancia(servico.distancia_km);
}

/** Deslocamento aproximado em km (leste, norte) entre dois pontos próximos. */
export function deslocamentoKm(origem, destino) {
  const rad = Math.PI / 180;
  const norte = (destino.lat - origem.lat) * 110.574;
  const leste = (destino.lon - origem.lon) * 111.32 * Math.cos(origem.lat * rad);
  return { leste, norte };
}

/** Direção em texto ("ao sudeste") a partir do deslocamento leste/norte. */
export function direcaoTexto({ leste, norte }) {
  if (Math.hypot(leste, norte) < 0.05) return "";
  const graus = (Math.atan2(leste, norte) * 180) / Math.PI;
  const indice = Math.round(((graus + 360) % 360) / 45) % 8;
  return PONTOS_CARDEAIS[indice];
}

/** Escolhe o passo dos anéis de modo que haja no máximo 3 anéis dentro do raio. */
export function passoDoAnel(raioKm) {
  for (const passo of PASSOS_ANEL_KM) {
    if (raioKm / passo <= 3) return passo;
  }
  return PASSOS_ANEL_KM[PASSOS_ANEL_KM.length - 1];
}

export function telefoneParaLink(telefone) {
  const digitos = String(telefone || "").replace(/[^\d+]/g, "");
  return digitos.length >= 3 ? `tel:${digitos}` : "";
}

export function linkComoChegar(servico) {
  const consulta = [servico.nome, servico.endereco, servico.municipio, servico.uf]
    .filter(Boolean)
    .join(", ");
  return `https://www.google.com/maps/search/?api=1&query=${encodeURIComponent(consulta)}`;
}

/** Remove a DEAM mais próxima da lista quando ela já aparece nos resultados. */
export function deamSeparada(resposta) {
  const deam = resposta?.deam_mais_proxima;
  if (!deam) return null;
  const chave = (s) => `${s.nome}|${s.endereco ?? ""}`;
  const jaNaLista = (resposta.servicos || []).some((s) => chave(s) === chave(deam));
  return jaNaLista ? null : deam;
}

/**
 * Posições do esquema. Origem no centro (0,0), norte para cima.
 * Retorna { raioKm, passoKm, aneis[], pontos[] } com coordenadas em unidades do viewBox.
 */
export function calcularEsquema(origem, servicos, raioDesenho = 100) {
  const itens = servicos.map((servico) => {
    const d = deslocamentoKm(origem, { lat: servico.latitude, lon: servico.longitude });
    return { servico, ...d, distancia: Math.hypot(d.leste, d.norte) };
  });
  const maior = Math.max(1, ...itens.map((i) => i.distancia));
  const passoKm = passoDoAnel(maior);
  const raioKm = Math.max(maior * 1.1, passoKm);
  const escala = raioDesenho / raioKm;

  const aneis = [];
  for (let km = passoKm; km <= raioKm * 1.001; km += passoKm) {
    aneis.push({ km, raio: km * escala });
  }
  const pontos = itens.map((i) => ({
    servico: i.servico,
    x: i.leste * escala,
    y: -i.norte * escala,
    distancia: i.distancia,
    direcao: direcaoTexto(i),
  }));
  return { raioKm, passoKm, aneis, pontos };
}

/* --- renderização ---------------------------------------------------------- */

function icone(nome) {
  return `<svg class="i" aria-hidden="true" focusable="false"><use href="#i-${nome}"></use></svg>`;
}

/** "de você" / "do centro de São Paulo/SP", para frases como "a partir de…". */
function partidaTexto(rotulo) {
  return rotulo === "você" ? "de você" : `do ${rotulo}`;
}

function htmlEsquema(esquema, rotuloOrigem = "você") {
  const aneis = esquema.aneis
    .map(
      (a) => `
      <circle class="radar__anel" r="${a.raio.toFixed(1)}"></circle>
      <text class="radar__rotulo" x="3" y="${(-a.raio + 11).toFixed(1)}">${escapar(formatarDistancia(a.km))}</text>`,
    )
    .join("");

  const pontos = esquema.pontos
    .map((p, i) => {
      const deam = p.servico.tipo === "deam" || p.servico.tipo === "nucleo_atendimento_mulher";
      return `
      <g class="radar__ponto${deam ? " radar__ponto--deam" : ""}" transform="translate(${p.x.toFixed(1)} ${p.y.toFixed(1)})">
        <circle r="10"></circle>
        <text y="4" text-anchor="middle">${i + 1}</text>
      </g>`;
    })
    .join("");

  const resumo = esquema.pontos
    .map((p, i) => {
      const direcao = p.direcao ? `, ${p.direcao}` : "";
      return `${i + 1}: ${p.servico.nome}, a ${formatarDistancia(p.distancia)}${direcao}`;
    })
    .join(". ");

  return `
    <figure class="radar">
      <svg viewBox="-125 -125 250 250" role="img" aria-label="Esquema de distância e direção a partir ${escapar(partidaTexto(rotuloOrigem))}. ${escapar(resumo)}">
        ${aneis}
        <path class="radar__eixo" d="M0 -118 V118 M-118 0 H118"></path>
        <text class="radar__norte" x="0" y="-112" text-anchor="middle">N</text>
        ${pontos}
        <g class="radar__voce">
          <circle r="6"></circle>
        </g>
      </svg>
      <figcaption>Esquema de distância e direção a partir ${escapar(partidaTexto(rotuloOrigem))} (norte para cima). Não é um mapa de ruas.</figcaption>
    </figure>`;
}

function htmlCartao(servico, indice, { mostrarDistancia, direcao, numerado }) {
  const rotulo = ROTULOS_TIPO[servico.tipo] || "Delegacia";
  const especializada = servico.tipo !== "delegacia_comum";
  const distancia = mostrarDistancia && servico.distancia_km != null
    ? `<span class="deleg__distancia">${escapar(rotuloDistancia(servico))}${direcao ? ` · ${escapar(direcao)}` : ""}</span>`
    : "";
  const tel = telefoneParaLink(servico.telefone);
  const telefone = tel
    ? `<a class="botao botao--primario botao--compacto" href="${escapar(tel)}">${icone("telefone")}Ligar ${escapar(servico.telefone)}</a>`
    : `<span class="deleg__sem-telefone">Telefone não informado. Ligue 180 para confirmar.</span>`;
  const aprox = servico.coordenada_verificada
    ? ""
    : `<p class="deleg__alerta">${icone("alerta")}<span>Localização aproximada. Confirme o endereço por telefone antes de ir.</span></p>`;

  return `
    <li class="deleg__cartao${especializada ? " deleg__cartao--deam" : ""}">
      <div class="deleg__topo">
        ${numerado ? `<span class="deleg__numero" aria-hidden="true">${indice + 1}</span>` : ""}
        <div class="deleg__titulos">
          <p class="deleg__rotulo">${escapar(rotulo)}</p>
          <h3 class="deleg__nome">${escapar(servico.nome)}</h3>
        </div>
        ${distancia}
      </div>
      <dl class="deleg__dados">
        ${servico.endereco ? `<div><dt>Endereço</dt><dd>${escapar(servico.endereco)}, ${escapar(servico.municipio)}/${escapar(servico.uf)}</dd></div>` : `<div><dt>Cidade</dt><dd>${escapar(servico.municipio)}/${escapar(servico.uf)}</dd></div>`}
        ${servico.horario ? `<div><dt>Horário</dt><dd>${escapar(servico.horario)}</dd></div>` : ""}
        <div><dt>Dados de</dt><dd>${escapar(String(servico.atualizado_em || "").split("-").reverse().join("/"))}</dd></div>
      </dl>
      ${aprox}
      <div class="deleg__acoes">
        ${telefone}
        <a class="botao botao--secundario botao--compacto" href="${escapar(linkComoChegar(servico))}" target="_blank" rel="noopener noreferrer">${icone("mapa")}Como chegar<span class="sr-only"> (abre o Google Maps em nova aba)</span></a>
      </div>
    </li>`;
}

/** Origem das distâncias: a localização da pessoa ou, na busca por cidade, o centro dela. */
export function origemDaResposta(resposta, origem) {
  if (origem) return { ...origem, rotulo: "você" };
  const ref = resposta?.referencia;
  if (!ref) return null;
  return { lat: ref.latitude, lon: ref.longitude, rotulo: ref.rotulo };
}

function temDadoDoOsm(resposta) {
  const todos = [...(resposta.servicos || []), resposta.deam_mais_proxima].filter(Boolean);
  return todos.some((s) => String(s.fonte_url || "").includes("openstreetmap.org"));
}

export function htmlResultado(resposta, origemBruta) {
  const servicos = resposta.servicos || [];
  const separada = deamSeparada(resposta);
  const origem = origemDaResposta(resposta, origemBruta);
  const comPonto = Boolean(origem);
  const doCentro = comPonto && origem.rotulo !== "você";

  const partes = [];

  if (resposta.aviso) {
    partes.push(`<p class="deleg__aviso" role="note">${icone("info")}<span>${escapar(resposta.aviso)}</span></p>`);
  }

  if (!servicos.length && !separada) {
    // O aviso da API já explica a ausência de resultados: não repetir.
    if (!resposta.aviso) {
      partes.push(
        `<p class="deleg__vazio">Não encontramos delegacias cadastradas para essa busca. Ligue 180 (Central de Atendimento à Mulher, 24 horas) para saber qual é a mais próxima.</p>`,
      );
    }
  } else {
    if (comPonto && servicos.length) partes.push(htmlEsquema(calcularEsquema(origem, servicos), origem.rotulo));

    if (separada) {
      partes.push(`
        <section class="deleg__destaque" aria-label="Delegacia da Mulher mais próxima">
          <h3 class="deleg__subtitulo">Delegacia da Mulher mais próxima</h3>
          <ul class="deleg__lista">${htmlCartao(separada, 0, {
            mostrarDistancia: comPonto,
            direcao: comPonto ? direcaoTexto(deslocamentoKm(origem, { lat: separada.latitude, lon: separada.longitude })) : "",
            numerado: false,
          })}</ul>
        </section>`);
    }

    if (servicos.length) {
      const itens = servicos
        .map((s, i) =>
          htmlCartao(s, i, {
            mostrarDistancia: comPonto,
            direcao: comPonto ? direcaoTexto(deslocamentoKm(origem, { lat: s.latitude, lon: s.longitude })) : "",
            numerado: comPonto,
          }),
        )
        .join("");
      partes.push(`
        <section aria-label="Delegacias encontradas">
          <h3 class="deleg__subtitulo">${doCentro ? "Mais próximas do centro da cidade" : comPonto ? "Mais próximas de você" : "No seu estado"}</h3>
          <ul class="deleg__lista">${itens}</ul>
        </section>`);
    }
  }

  const emergencia = resposta.emergencia || { policia_militar: "190", central_mulher: "180" };
  partes.push(`
    <div class="deleg__emergencia">
      <a class="telefone telefone--principal" href="tel:${escapar(emergencia.policia_militar)}">
        <span class="telefone__numero">${escapar(emergencia.policia_militar)}</span>
        <span class="telefone__nome">Polícia · perigo agora</span>
      </a>
      <a class="telefone telefone--verde" href="tel:${escapar(emergencia.central_mulher)}">
        <span class="telefone__numero">${escapar(emergencia.central_mulher)}</span>
        <span class="telefone__nome">Central da Mulher</span>
      </a>
    </div>
    ${temDadoDoOsm(resposta) ? `<p class="dialogo__nota">Parte dos endereços vem do OpenStreetMap, mantido por voluntários, e pode estar desatualizada. © <a class="link" href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener noreferrer">contribuidores do OpenStreetMap</a>.</p>` : ""}
    <p class="dialogo__nota">${escapar(resposta.aviso_legal || "Confirme o endereço e o horário por telefone antes de ir. Em perigo imediato, ligue 190.")}</p>`);

  return partes.join("");
}

/* --- painel ---------------------------------------------------------------- */

/**
 * Liga o diálogo. `contexto` traz dependências do app para evitar import circular:
 *   api: cliente (servicosProximos), modo(): "api" | "demo",
 *   abrirDialogo/fecharDialogo, anunciar.
 */
export function criarPainelDelegacias(contexto) {
  const dialogo = document.getElementById("dialogo-delegacias");
  if (!dialogo) return { abrir() {} };

  const $ = (id) => document.getElementById(id);
  const botaoLocal = $("deleg-usar-local");
  const formCidade = $("deleg-form-cidade");
  const selectUf = $("deleg-uf");
  const campoCidade = $("deleg-municipio");
  const status = $("deleg-status");
  const resultado = $("deleg-resultado");
  const limpar = $("deleg-limpar");
  const sair = $("deleg-sair");

  selectUf.innerHTML =
    `<option value="">UF</option>` + UFS.map((uf) => `<option value="${uf}">${uf}</option>`).join("");

  let busca = 0;

  function mostrarStatus(texto, { erro = false } = {}) {
    status.textContent = texto;
    status.dataset.tipo = erro ? "erro" : "info";
    status.hidden = !texto;
    if (texto) contexto.anunciar?.(texto);
  }

  function limparTudo() {
    busca += 1; // invalida buscas em andamento
    resultado.innerHTML = "";
    resultado.hidden = true;
    limpar.hidden = true;
    mostrarStatus("");
    botaoLocal.disabled = false;
    formCidade.querySelectorAll("button, input, select").forEach((e) => (e.disabled = false));
  }

  function ocupar(ocupado) {
    botaoLocal.disabled = ocupado;
    formCidade.querySelectorAll("button, input, select").forEach((e) => (e.disabled = ocupado));
  }

  async function consultar(corpo, origem) {
    if (contexto.modo() === "demo") {
      mostrarStatus(
        "Modo demonstração: a busca de delegacias precisa da API conectada. Ligue 190 em perigo ou 180 para orientação.",
        { erro: true },
      );
      return;
    }
    const minha = ++busca;
    ocupar(true);
    resultado.hidden = true;
    mostrarStatus("Buscando delegacias…");
    try {
      const resposta = await contexto.api.servicosProximos({ ...corpo, limit: LIMITE_RESULTADOS });
      if (minha !== busca) return;
      resultado.innerHTML = htmlResultado(resposta, origem);
      resultado.hidden = false;
      limpar.hidden = false;
      mostrarStatus("");
      const total = (resposta.servicos || []).length;
      contexto.anunciar?.(`${total} delegacias encontradas.`);
      resultado.scrollIntoView({ block: "start" });
    } catch (erro) {
      if (minha !== busca) return;
      const indisponivel = erro?.status === 503 || erro?.tipo === "rede" || erro?.tipo === "tempo";
      mostrarStatus(
        indisponivel
          ? "Não conseguimos consultar as delegacias agora. Ligue 190 em perigo ou 180 (24 horas) para saber a mais próxima."
          : "Não entendemos essa busca. Confira a UF e o nome da cidade e tente de novo.",
        { erro: true },
      );
    } finally {
      if (minha === busca) ocupar(false);
    }
  }

  function usarLocalizacao() {
    if (!("geolocation" in navigator)) {
      mostrarStatus("Este aparelho não permite localização. Informe sua cidade abaixo.", { erro: true });
      campoCidade.focus();
      return;
    }
    ocupar(true);
    mostrarStatus("Aguardando a permissão de localização do aparelho…");
    navigator.geolocation.getCurrentPosition(
      (posicao) => {
        const origem = {
          lat: arredondarCoordenada(posicao.coords.latitude),
          lon: arredondarCoordenada(posicao.coords.longitude),
        };
        ocupar(false);
        consultar({ lat: origem.lat, lon: origem.lon }, origem);
      },
      (falha) => {
        ocupar(false);
        const negada = falha?.code === 1;
        mostrarStatus(
          negada
            ? "Sem problema, a localização não foi usada. Informe sua cidade abaixo."
            : "Não foi possível obter a localização. Informe sua cidade abaixo.",
          { erro: true },
        );
        selectUf.focus();
      },
      { enableHighAccuracy: false, timeout: 10000, maximumAge: 0 },
    );
  }

  botaoLocal.addEventListener("click", usarLocalizacao);

  formCidade.addEventListener("submit", (evento) => {
    evento.preventDefault();
    const uf = selectUf.value.trim();
    const municipio = campoCidade.value.trim();
    if (!uf || !municipio) {
      mostrarStatus("Escolha a UF e escreva o nome da cidade.", { erro: true });
      (uf ? campoCidade : selectUf).focus();
      return;
    }
    consultar({ uf, municipio }, null);
  });

  limpar.addEventListener("click", () => {
    limparTudo();
    botaoLocal.focus();
  });

  sair.addEventListener("click", () => {
    limparTudo();
    campoCidade.value = "";
    selectUf.value = "";
    contexto.fecharDialogo(dialogo);
    window.location.replace(SAIDA_RAPIDA_URL);
  });

  // Fechar o painel apaga localização e resultado da memória.
  dialogo.addEventListener("close", () => {
    limparTudo();
    campoCidade.value = "";
    selectUf.value = "";
  });

  return {
    abrir() {
      limparTudo();
      contexto.abrirDialogo(dialogo);
    },
  };
}
