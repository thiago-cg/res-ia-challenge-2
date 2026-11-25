/**
 * ZELIA · mapa 3D das delegacias (opcional).
 *
 * Só é carregado quando a usuária toca em "Ver em 3D". MapLibre GL (mapa) e deck.gl (colunas e
 * círculo de precisão) ficam no próprio servidor (vendor/); do exterior vêm apenas os blocos
 * vetoriais do mapa (OpenFreeMap, dados do OpenStreetMap), e o aviso na tela diz isso.
 * A posição da usuária nunca é gravada: o mapa é montado e descartado na tela.
 *
 * Mesma interface do mapa.js: mostrarMapa3D(alvo, { servicos, origem, aoSelecionar })
 * devolve { destruir(), marcarVoce(), focar(indice) }.
 */

import { agruparPorPonto, rotuloCentro } from "./mapa.js";

export const ESTILO_URL = "https://tiles.openfreemap.org/styles/liberty";
const ATRIBUICAO =
  '<a href="https://openfreemap.org" target="_blank" rel="noopener noreferrer">OpenFreeMap</a> ' +
  '© <a href="https://openmaptiles.org/" target="_blank" rel="noopener noreferrer">OpenMapTiles</a> ' +
  'Dados © <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener noreferrer">contribuidores do OpenStreetMap</a>';

const MAPLIBRE_JS = new URL("../vendor/maplibre/maplibre-gl.js", import.meta.url).href;
const MAPLIBRE_CSS = new URL("../vendor/maplibre/maplibre-gl.css", import.meta.url).href;
const DECK_JS = new URL("../vendor/deckgl/deckgl.min.js", import.meta.url).href;

const INCLINACAO = 55;
const GIRO = -20;
const ALTURA_COLUNA = { delegacia: 140, deam: 220 };
const COR_DELEGACIA = [31, 107, 84, 210]; // verde escuro da marca
const COR_DEAM = [36, 87, 214, 220]; // azul da marca
const COR_PRECISAO = [36, 87, 214];

let carregando = null;

function carregarScript(src) {
  return new Promise((resolver, rejeitar) => {
    const js = document.createElement("script");
    js.src = src;
    js.onload = resolver;
    js.onerror = () => rejeitar(new Error(src));
    document.head.append(js);
  });
}

function carregarBibliotecas() {
  if (globalThis.maplibregl && globalThis.deck) return Promise.resolve();
  if (carregando) return carregando;
  carregando = (async () => {
    if (!document.querySelector(`link[href="${MAPLIBRE_CSS}"]`)) {
      const css = document.createElement("link");
      css.rel = "stylesheet";
      css.href = MAPLIBRE_CSS;
      document.head.append(css);
    }
    await carregarScript(MAPLIBRE_JS);
    await carregarScript(DECK_JS);
  })().catch((erro) => {
    carregando = null;
    throw erro;
  });
  return carregando;
}

/** O 3D precisa de WebGL; sem ele, a tela volta para o mapa 2D. */
export function temWebGL() {
  try {
    const tela = document.createElement("canvas");
    return Boolean(tela.getContext("webgl2") || tela.getContext("webgl"));
  } catch {
    return false;
  }
}

/** Baixa só os arquivos do próprio servidor para o 3D abrir na hora. */
export function precarregar() {
  for (const [href, tipo] of [
    [MAPLIBRE_JS, "script"],
    [MAPLIBRE_CSS, "style"],
    [DECK_JS, "script"],
  ]) {
    if (document.querySelector(`link[rel="preload"][href="${href}"]`)) continue;
    const link = document.createElement("link");
    link.rel = "preload";
    link.as = tipo;
    link.href = href;
    document.head.append(link);
  }
}

function escapar(texto) {
  return String(texto ?? "").replace(/[&<>"']/g, (c) => `&#${c.charCodeAt(0)};`);
}

function elementoPino(classe, html = "<span></span>", largo = false) {
  const el = document.createElement("div");
  el.className = classe;
  el.innerHTML = html;
  el.style.width = largo ? "44px" : "30px";
  el.style.height = "30px";
  return el;
}

/** Garante prédios em 3D mesmo que o estilo do provedor não traga a camada. */
function garantirPredios(mapa) {
  const estilo = mapa.getStyle();
  if (!estilo?.layers || estilo.layers.some((c) => c.type === "fill-extrusion")) return;
  const fonte = Object.entries(estilo.sources || {}).find(([, s]) => s.type === "vector")?.[0];
  if (!fonte) return;
  mapa.addLayer({
    id: "zelia-predios-3d",
    type: "fill-extrusion",
    source: fonte,
    "source-layer": "building",
    minzoom: 14,
    paint: {
      "fill-extrusion-color": "#d9d4c7",
      "fill-extrusion-height": ["coalesce", ["get", "render_height"], 8],
      "fill-extrusion-base": ["coalesce", ["get", "render_min_height"], 0],
      "fill-extrusion-opacity": 0.85,
    },
  });
}

export async function mostrarMapa3D(alvo, { servicos, origem, aoSelecionar }) {
  if (!temWebGL()) throw new Error("webgl");
  await carregarBibliotecas();
  const { maplibregl, deck } = globalThis;
  alvo.innerHTML = "";

  const reduzMovimento = matchMedia("(prefers-reduced-motion: reduce)").matches;
  const pontos = [];
  if (origem) pontos.push([origem.lon, origem.lat]);
  const grupos = agruparPorPonto(servicos);
  grupos.forEach((g) => pontos.push([g.lon, g.lat]));
  const inicio = pontos[0] || [-47.88, -15.79];

  const mapa = new maplibregl.Map({
    container: alvo,
    style: ESTILO_URL,
    center: inicio,
    zoom: pontos.length ? 14 : 4,
    pitch: INCLINACAO,
    bearing: GIRO,
    maxPitch: 70,
    cooperativeGestures: true,
    attributionControl: { compact: true, customAttribution: ATRIBUICAO },
    canvasContextAttributes: { antialias: true },
    fadeDuration: reduzMovimento ? 0 : 300,
  });
  mapa.addControl(new maplibregl.NavigationControl({ visualizePitch: true }), "top-right");

  // Sem os blocos do mapa (rede lenta ou bloqueada), a lista continua valendo.
  let carregou = false;
  const avisar = () => {
    if (carregou || alvo.querySelector(".mapa__aviso")) return;
    const aviso = document.createElement("p");
    aviso.className = "mapa__aviso";
    aviso.textContent = "Não foi possível carregar o mapa 3D agora. A lista abaixo continua valendo.";
    alvo.append(aviso);
  };
  const espera = window.setTimeout(avisar, 9000);
  mapa.on("error", (e) => {
    if (!carregou && e?.error) avisar();
  });
  mapa.on("load", () => {
    carregou = true;
    window.clearTimeout(espera);
    try {
      garantirPredios(mapa);
    } catch {
      /* o mapa segue sem os prédios */
    }
  });

  let precisao = null; // { lon, lat, raio }
  const sobreposicao = new deck.MapboxOverlay({ interleaved: false, layers: [] });
  mapa.addControl(sobreposicao);

  function desenharCamadas() {
    const camadas = [
      new deck.ColumnLayer({
        id: "delegacias",
        data: grupos.map((g) => ({
          lon: g.lon,
          lat: g.lat,
          especial: g.itens.some((i) => i.servico.tipo !== "delegacia_comum"),
        })),
        getPosition: (d) => [d.lon, d.lat],
        getElevation: (d) => (d.especial ? ALTURA_COLUNA.deam : ALTURA_COLUNA.delegacia),
        getFillColor: (d) => (d.especial ? COR_DEAM : COR_DELEGACIA),
        radius: 10,
        diskResolution: 24,
        extruded: true,
        pickable: false,
        material: { ambient: 0.6, diffuse: 0.6, shininess: 24 },
      }),
    ];
    if (precisao) {
      camadas.push(
        new deck.ScatterplotLayer({
          id: "precisao",
          data: [precisao],
          getPosition: (d) => [d.lon, d.lat],
          getRadius: (d) => d.raio,
          radiusUnits: "meters",
          getFillColor: [...COR_PRECISAO, 36],
          getLineColor: [...COR_PRECISAO, 110],
          stroked: true,
          lineWidthMinPixels: 1,
          pickable: false,
        }),
      );
    }
    sobreposicao.setProps({ layers: camadas });
  }

  function rotuloVoce(raio) {
    return Number.isFinite(raio) && raio >= 1 ? `Você (±${Math.round(raio)} m)` : "Você";
  }

  const marcadoresOrigem = [];
  function pinoOrigem(lat, lon, { voce, rotulo, raio }) {
    const el = elementoPino(voce ? "mapa__voce" : "mapa__centro");
    el.style.width = "22px";
    el.style.height = "22px";
    el.setAttribute("role", "img");
    el.setAttribute("aria-label", rotulo);
    const marcador = new maplibregl.Marker({ element: el, anchor: "center" }).setLngLat([lon, lat]).addTo(mapa);
    marcador.setPopup(new maplibregl.Popup({ offset: 14, closeButton: false }).setText(rotulo));
    marcadoresOrigem.push(marcador);
    if (voce && Number.isFinite(raio) && raio >= 20) {
      precisao = { lon, lat, raio };
      desenharCamadas();
    }
    return marcador;
  }

  let pinoVoce = null;
  if (origem) {
    const voce = origem.rotulo === "você";
    const marcador = pinoOrigem(origem.lat, origem.lon, {
      voce,
      raio: origem.precisao,
      rotulo: voce ? rotuloVoce(origem.precisao) : rotuloCentro(origem.rotulo),
    });
    if (voce) pinoVoce = marcador;
  }

  const marcadores = new Map(); // índice do serviço -> { marcador, lon, lat }
  for (const grupo of grupos) {
    const numeros = grupo.itens.map((i) => i.indice + 1).join("·");
    const especial = grupo.itens.some((i) => i.servico.tipo !== "delegacia_comum");
    const largo = grupo.itens.length > 1;
    const el = elementoPino(
      `mapa__pino${especial ? " mapa__pino--deam" : ""}${largo ? " mapa__pino--grupo" : ""}`,
      `<span>${numeros}</span>`,
      largo,
    );
    el.setAttribute("role", "button");
    el.setAttribute("tabindex", "0");
    el.setAttribute("aria-label", grupo.itens.map((i) => `${i.indice + 1}. ${i.servico.nome}`).join(" / "));
    const popup = new maplibregl.Popup({ offset: 20, maxWidth: "260px" }).setHTML(
      grupo.itens
        .map((i) => `<strong>${i.indice + 1}. ${escapar(i.servico.nome)}</strong><br>${escapar(i.servico.endereco || "")}`)
        .join("<hr>"),
    );
    const marcador = new maplibregl.Marker({ element: el, anchor: "center" })
      .setLngLat([grupo.lon, grupo.lat])
      .setPopup(popup)
      .addTo(mapa);
    const selecionar = () => aoSelecionar?.(grupo.itens[0].indice);
    el.addEventListener("click", selecionar);
    el.addEventListener("keydown", (e) => {
      if (e.key === "Enter" || e.key === " ") {
        e.preventDefault();
        marcador.togglePopup();
        selecionar();
      }
    });
    grupo.itens.forEach((i) => marcadores.set(i.indice, { marcador, lon: grupo.lon, lat: grupo.lat }));
  }
  desenharCamadas();

  function enquadrar(extra = []) {
    const todos = [...pontos, ...extra];
    if (todos.length > 1) {
      const limites = todos.reduce(
        (b, p) => b.extend(p),
        new maplibregl.LngLatBounds(todos[0], todos[0]),
      );
      mapa.fitBounds(limites, {
        padding: 56,
        maxZoom: 15.5,
        pitch: INCLINACAO,
        bearing: GIRO,
        duration: reduzMovimento ? 0 : 900,
      });
    } else if (todos.length === 1) {
      mapa.jumpTo({ center: todos[0], zoom: 15, pitch: INCLINACAO, bearing: GIRO });
    }
  }
  mapa.once("load", () => enquadrar());
  const observador = new ResizeObserver(() => mapa.resize());
  observador.observe(alvo);

  async function marcarVoce() {
    if (!("geolocation" in navigator)) return false;
    try {
      const { coords } = await new Promise((resolver, rejeitar) =>
        navigator.geolocation.getCurrentPosition(resolver, rejeitar, {
          enableHighAccuracy: true,
          timeout: 10000,
          maximumAge: 0,
        }),
      ).catch((falha) => {
        if (falha?.code === 1) throw falha;
        return new Promise((resolver, rejeitar) =>
          navigator.geolocation.getCurrentPosition(resolver, rejeitar, { timeout: 8000, maximumAge: 0 }),
        );
      });
      pinoVoce?.remove();
      precisao = null;
      pinoVoce = pinoOrigem(coords.latitude, coords.longitude, {
        voce: true,
        raio: coords.accuracy,
        rotulo: rotuloVoce(coords.accuracy),
      });
      desenharCamadas();
      enquadrar([[coords.longitude, coords.latitude]]);
      return true;
    } catch {
      return false;
    }
  }

  function focar(indice) {
    const alvoPino = marcadores.get(indice);
    if (!alvoPino) return;
    mapa.easeTo({
      center: [alvoPino.lon, alvoPino.lat],
      zoom: Math.max(mapa.getZoom(), 16),
      pitch: INCLINACAO,
      duration: reduzMovimento ? 0 : 700,
    });
    if (!alvoPino.marcador.getPopup().isOpen()) alvoPino.marcador.togglePopup();
  }

  return {
    destruir: () => {
      window.clearTimeout(espera);
      observador.disconnect();
      marcadoresOrigem.length = 0;
      mapa.remove();
    },
    marcarVoce,
    focar,
  };
}
