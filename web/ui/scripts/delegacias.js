/**
 * ZELIA · delegacias mais próximas
 *
 * Painel (diálogo) que consulta POST /services/nearby e mostra o resultado como
 * lista de cartões e, se a usuária pedir, um mapa de ruas (mapa.js). O mapa usa
 * blocos de imagem do OpenStreetMap, que revelam a região mostrada e o IP a esse
 * serviço; por isso ele só é carregado depois de um toque, com aviso na tela.
 *
 * Privacidade da localização:
 *  - só é pedida quando a usuária toca em "Usar minha localização" (ou "Marcar onde estou" no mapa);
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

const LIMITE_RESULTADOS = 5;
export const SAIDA_RAPIDA_URL = "https://www.google.com.br/";

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

/**
 * Lista única por proximidade. A DEAM mais próxima entra na posição que a distância dá a ela
 * (e é sempre mostrada, mesmo fora das primeiras); sem distância, mantém a ordem da API.
 */
export function servicosOrdenados(resposta) {
  const lista = [...(resposta?.servicos || [])];
  const deam = deamSeparada(resposta);
  if (deam) lista.push(deam);
  return ordenarPorDistancia(semDuplicatas(lista));
}

/** "11ª DP" e "11ª Delegacia (…) – Núcleo de Atendimento" são o mesmo lugar: fica o Núcleo. */
function numeroDaDelegacia(servico) {
  return String(servico.nome || "").match(/^0*(\d+)\s*ª/)?.[1] ?? null;
}

export function semDuplicatas(lista) {
  const mesmoLugar = (a, b) =>
    Math.abs(a.latitude - b.latitude) < 0.002 && Math.abs(a.longitude - b.longitude) < 0.002;
  return lista.filter((s, i) => {
    const numero = numeroDaDelegacia(s);
    if (!numero || s.tipo !== "delegacia_comum") return true;
    return !lista.some(
      (o, j) =>
        j !== i &&
        o.tipo === "nucleo_atendimento_mulher" &&
        numeroDaDelegacia(o) === numero &&
        o.uf === s.uf &&
        mesmoLugar(o, s),
    );
  });
}

function ordenarPorDistancia(lista) {
  const comDistancia = lista.every((s) => typeof s.distancia_km === "number");
  return comDistancia ? [...lista].sort((a, b) => a.distancia_km - b.distancia_km) : lista;
}

/** Remove a DEAM mais próxima da lista quando ela já aparece nos resultados. */
export function deamSeparada(resposta) {
  const deam = resposta?.deam_mais_proxima;
  if (!deam) return null;
  const chave = (s) => `${s.nome}|${s.endereco ?? ""}`;
  const jaNaLista = (resposta.servicos || []).some((s) => chave(s) === chave(deam));
  return jaNaLista ? null : deam;
}

/* --- renderização ---------------------------------------------------------- */

function icone(nome) {
  return `<svg class="i" aria-hidden="true" focusable="false"><use href="#i-${nome}"></use></svg>`;
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
    : `<span class="deleg__sem-telefone">Sem telefone cadastrado. Ligue 180 para confirmar.</span>`;
  const cidade = `${servico.municipio}/${servico.uf}`;
  const local = !servico.endereco
    ? cidade
    : servico.endereco.toLowerCase().includes(String(servico.municipio).toLowerCase())
      ? servico.endereco
      : `${servico.endereco}, ${cidade}`;
  const notas = [
    servico.horario,
    servico.coordenada_verificada ? "" : "Localização aproximada: confirme o endereço por telefone antes de ir.",
    `Dados de ${String(servico.atualizado_em || "").split("-").reverse().join("/")}`,
  ].filter(Boolean);

  return `
    <li class="deleg__cartao${especializada ? " deleg__cartao--deam" : ""}" data-indice="${indice}">
      ${numerado ? `<span class="deleg__numero" aria-hidden="true">${indice + 1}</span>` : ""}
      <div class="deleg__corpo">
        <div class="deleg__topo">
          <h3 class="deleg__nome">${escapar(servico.nome)}</h3>
          ${distancia}
        </div>
        <p class="deleg__rotulo">${escapar(rotulo)}</p>
        <p class="deleg__endereco">${escapar(local)}</p>
        <p class="deleg__nota">${notas.map(escapar).join(" · ")}</p>
        <div class="deleg__acoes">
          ${telefone}
          <a class="botao botao--secundario botao--compacto" href="${escapar(linkComoChegar(servico))}" target="_blank" rel="noopener noreferrer">Como chegar<span class="sr-only"> (abre o Google Maps em nova aba)</span></a>
        </div>
      </div>
    </li>`;
}

/** Origem das distâncias: a localização da pessoa ou, na busca por cidade, o centro dela. */
export function origemDaResposta(resposta, origem) {
  // O pino usa a posição exata do aparelho; só a consulta à API usa a arredondada.
  if (origem) return { ...origem, ...(origem.exata ?? {}), rotulo: "você" };
  const ref = resposta?.referencia;
  if (!ref) return null;
  return { lat: ref.latitude, lon: ref.longitude, rotulo: ref.rotulo };
}

function temDadoDoOsm(resposta) {
  const todos = [...(resposta.servicos || []), resposta.deam_mais_proxima].filter(Boolean);
  return todos.some((s) => String(s.fonte_url || "").includes("openstreetmap.org"));
}

/** Espaço do mapa: só carrega o mapa de ruas (e o OpenStreetMap) quando a usuária pede. */
export function htmlBlocoMapa(comPonto) {
  return `
    <section class="deleg__mapa" aria-label="Mapa de ruas">
      <div class="deleg__mapa-caixa" data-mapa-caixa role="region" aria-label="Mapa com as delegacias" hidden></div>
      <div class="deleg__mapa-pedido" data-mapa-pedido>
        <p>Sua localização exata não sai do seu aparelho. O mapa só pede as imagens da região.</p>
        <button class="botao botao--secundario" type="button" data-abrir-mapa>Abrir o mapa</button>
      </div>
      ${comPonto ? "" : `<button class="botao botao--fantasma botao--compacto" type="button" data-marcar-voce hidden>Marcar onde estou</button>`}
    </section>`;
}

export function htmlResultado(resposta, origemBruta) {
  const servicos = servicosOrdenados(resposta);
  const origem = origemDaResposta(resposta, origemBruta);
  const comPonto = Boolean(origem);
  const doCentro = comPonto && origem.rotulo !== "você";

  const partes = [];

  if (resposta.aviso) {
    partes.push(`<p class="deleg__aviso" role="note">${icone("info")}<span>${escapar(resposta.aviso)}</span></p>`);
  }

  if (!servicos.length) {
    // O aviso da API já explica a ausência de resultados: não repetir.
    if (!resposta.aviso) {
      partes.push(
        `<p class="deleg__vazio">Não encontramos delegacias cadastradas para essa busca. Ligue 180 (Central de Atendimento à Mulher, 24 horas) para saber qual é a mais próxima.</p>`,
      );
    }
  } else {
    partes.push(htmlBlocoMapa(origem?.rotulo === "você"));
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

/**
 * Posição atual do aparelho, a mais precisa disponível (GPS quando houver). Se o GPS demorar
 * ou falhar, tenta uma posição aproximada (Wi-Fi/rede). Só "negada" (código 1) encerra de vez.
 */
export function pedirPosicao(geolocation) {
  const tentar = (opcoes) =>
    new Promise((resolver, rejeitar) => geolocation.getCurrentPosition(resolver, rejeitar, opcoes));
  return tentar({ enableHighAccuracy: true, timeout: 10000, maximumAge: 0 }).catch((falha) => {
    if (falha?.code === 1) throw falha;
    return tentar({ enableHighAccuracy: false, timeout: 8000, maximumAge: 0 });
  });
}

/** Posição exata do aparelho (não é enviada à API) e a arredondada (a que vai na consulta). */
export function origemDaPosicao(posicao) {
  const { latitude, longitude, accuracy } = posicao.coords;
  return {
    lat: arredondarCoordenada(latitude),
    lon: arredondarCoordenada(longitude),
    exata: { lat: latitude, lon: longitude, precisao: Number.isFinite(accuracy) ? accuracy : null },
  };
}

/** "granted" | "prompt" | "denied". Sem a API de permissões, tratamos como "prompt". */
export async function estadoPermissao() {
  try {
    const r = await navigator.permissions.query({ name: "geolocation" });
    return r.state;
  } catch {
    return "prompt";
  }
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

  let ultima = null; // só na memória da tela; some ao limpar ou fechar
  let destruirMapa = null;

  function fecharMapa() {
    destruirMapa?.();
    destruirMapa = null;
  }

  /** Tocar num pino destaca o cartão da mesma delegacia na lista. */
  function destacarCartao(indice) {
    const cartao = resultado.querySelector(`.deleg__cartao[data-indice="${indice}"]`);
    if (!cartao) return;
    resultado.querySelectorAll(".deleg__cartao--ativo").forEach((el) => el.classList.remove("deleg__cartao--ativo"));
    cartao.classList.add("deleg__cartao--ativo");
    cartao.scrollIntoView({ block: "center", behavior: "smooth" });
  }

  async function abrirMapa(botao) {
    const secao = botao.closest(".deleg__mapa");
    const caixa = secao?.querySelector("[data-mapa-caixa]");
    const pedido = secao?.querySelector("[data-mapa-pedido]");
    if (!caixa || !ultima) return;
    botao.disabled = true;
    botao.textContent = "Carregando o mapa…";
    try {
      const { mostrarMapa } = await import("./mapa.js");
      caixa.hidden = false;
      fecharMapa();
      const mapa = await mostrarMapa(caixa, {
        servicos: servicosOrdenados(ultima.resposta),
        origem: origemDaResposta(ultima.resposta, ultima.origem),
        aoSelecionar: destacarCartao,
      });
      destruirMapa = mapa.destruir;
      // Tocar no número do cartão leva ao pino correspondente.
      resultado.querySelectorAll(".deleg__numero").forEach((numero) => {
        const indice = Number(numero.closest(".deleg__cartao")?.dataset.indice);
        numero.setAttribute("role", "button");
        numero.setAttribute("tabindex", "0");
        numero.setAttribute("aria-label", `Mostrar a delegacia ${indice + 1} no mapa`);
        numero.classList.add("deleg__numero--botao");
        const ir = () => {
          mapa.focar(indice);
          caixa.scrollIntoView({ block: "center", behavior: "smooth" });
        };
        numero.addEventListener("click", ir);
        numero.addEventListener("keydown", (e) => {
          if (e.key === "Enter" || e.key === " ") {
            e.preventDefault();
            ir();
          }
        });
      });
      pedido.hidden = true;
      const marcar = secao.querySelector("[data-marcar-voce]");
      if (marcar) {
        const permissao = await estadoPermissao();
        if (permissao === "granted") {
          // Ela já permitiu antes: o navegador não pergunta de novo, o pino aparece sozinho.
          mapa.marcarVoce();
        } else if (permissao === "prompt") {
          marcar.hidden = false;
          marcar.onclick = async () => {
            marcar.disabled = true;
            const ok = await mapa.marcarVoce();
            marcar.disabled = false;
            marcar.textContent = ok ? "Atualizar minha posição" : "Não foi possível obter a localização";
          };
        }
        // "denied": respeita a escolha, sem botão e sem insistir.
      }
    } catch {
      caixa.hidden = true;
      botao.disabled = false;
      botao.textContent = "Não foi possível abrir o mapa. Tentar de novo";
    }
  }

  resultado.addEventListener("click", (evento) => {
    const botao = evento.target.closest?.("[data-abrir-mapa]");
    if (botao) abrirMapa(botao);
  });

  function limparTudo() {
    busca += 1; // invalida buscas em andamento
    fecharMapa();
    ultima = null;
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
      fecharMapa();
      ultima = { resposta, origem };
      resultado.innerHTML = htmlResultado(resposta, origem);
      resultado.hidden = false;
      // Só arquivos do nosso servidor: o mapa abre na hora, sem falar com terceiros antes do toque.
      (window.requestIdleCallback || ((f) => setTimeout(f, 300)))(() =>
        import("./mapa.js").then((m) => m.precarregar()).catch(() => {}),
      );
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

  async function usarLocalizacao() {
    if ((await estadoPermissao()) === "denied") {
      mostrarStatus(
        "A localização está bloqueada neste aparelho. Você pode liberar nas configurações do navegador ou informar sua cidade abaixo.",
        { erro: true },
      );
      selectUf.focus();
      return;
    }
    if (!("geolocation" in navigator)) {
      mostrarStatus("Este aparelho não permite localização. Informe sua cidade abaixo.", { erro: true });
      campoCidade.focus();
      return;
    }
    // Se ela buscar por cidade enquanto o aparelho ainda procura o GPS, esta resposta é ignorada.
    const minha = ++busca;
    botaoLocal.disabled = true;
    mostrarStatus("Obtendo sua localização… Se demorar, você pode buscar pela cidade.");
    try {
      const origem = origemDaPosicao(await pedirPosicao(navigator.geolocation));
      if (minha !== busca) return;
      botaoLocal.disabled = false;
      consultar({ lat: origem.lat, lon: origem.lon }, origem);
    } catch (falha) {
      if (minha !== busca) return;
      botaoLocal.disabled = false;
      const negada = falha?.code === 1;
      mostrarStatus(
        negada
          ? "Sem problema, a localização não foi usada. Informe sua cidade abaixo."
          : "Não foi possível obter a localização. Informe sua cidade abaixo.",
        { erro: true },
      );
      selectUf.focus();
    }
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
