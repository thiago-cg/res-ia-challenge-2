/**
 * ZELIA · mapa de ruas das delegacias (opcional).
 *
 * Só é carregado quando a usuária toca em "Ver no mapa de ruas". Até lá, nada de
 * terceiros é baixado. O Leaflet fica no próprio servidor (vendor/leaflet); só os
 * blocos de imagem do mapa vêm do OpenStreetMap, e o aviso na tela diz isso.
 * A posição da usuária nunca é gravada: o mapa é montado e descartado na tela.
 */

const TILES_URL = "https://tile.openstreetmap.org/{z}/{x}/{y}.png";
const ATRIBUICAO =
  '© <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener noreferrer">contribuidores do OpenStreetMap</a>';
const LEAFLET_JS = new URL("../vendor/leaflet/leaflet.js", import.meta.url).href;
const LEAFLET_CSS = new URL("../vendor/leaflet/leaflet.css", import.meta.url).href;

let carregando = null;

function carregarLeaflet() {
  if (window.L) return Promise.resolve(window.L);
  if (carregando) return carregando;
  carregando = new Promise((resolver, rejeitar) => {
    const css = document.createElement("link");
    css.rel = "stylesheet";
    css.href = LEAFLET_CSS;
    document.head.append(css);
    const js = document.createElement("script");
    js.src = LEAFLET_JS;
    js.onload = () => resolver(window.L);
    js.onerror = () => {
      carregando = null;
      rejeitar(new Error("leaflet"));
    };
    document.head.append(js);
  });
  return carregando;
}

function escapar(texto) {
  return String(texto ?? "").replace(/[&<>"']/g, (c) => `&#${c.charCodeAt(0)};`);
}

/** Rótulo curto do ponto de partida da busca por cidade: "Centro de Guará". */
export function rotuloCentro(rotulo) {
  const limpo = String(rotulo || "")
    .replace(/^centro aproximado de /i, "")
    .replace(/^centro de /i, "")
    .replace(/\/[A-Z]{2}$/, "");
  return `Centro de ${limpo}`;
}

/** Junta serviços praticamente no mesmo ponto (≈10 m) para os pinos não ficarem um sobre o outro. */
export function agruparPorPonto(servicos) {
  const grupos = new Map();
  servicos.forEach((servico, indice) => {
    const chave = `${servico.latitude.toFixed(4)},${servico.longitude.toFixed(4)}`;
    if (!grupos.has(chave)) grupos.set(chave, { lat: servico.latitude, lon: servico.longitude, itens: [] });
    grupos.get(chave).itens.push({ servico, indice });
  });
  return [...grupos.values()];
}

/** Baixa só os arquivos do próprio servidor (sem terceiros) para o mapa abrir na hora. */
export function precarregar() {
  for (const [href, tipo] of [
    [LEAFLET_JS, "script"],
    [LEAFLET_CSS, "style"],
  ]) {
    if (document.querySelector(`link[rel="preload"][href="${href}"]`)) continue;
    const link = document.createElement("link");
    link.rel = "preload";
    link.as = tipo;
    link.href = href;
    document.head.append(link);
  }
}

/**
 * Desenha o mapa em `alvo`. `origem` ({lat, lon, rotulo, precisao}) pode ser null.
 * `aoSelecionar(indice)` é chamado quando a usuária toca num pino.
 * Devolve { destruir(), marcarVoce(), focar(indice) }.
 */
export async function mostrarMapa(alvo, { servicos, origem, aoSelecionar }) {
  const L = await carregarLeaflet();
  alvo.innerHTML = "";
  const mapa = L.map(alvo, {
    zoomControl: true,
    attributionControl: true,
    scrollWheelZoom: false,
    zoomSnap: 0.5,
  });
  const camada = L.tileLayer(TILES_URL, {
    maxZoom: 18,
    attribution: ATRIBUICAO,
    referrerPolicy: "no-referrer",
    keepBuffer: 4,
  }).addTo(mapa);

  // Sem as imagens do mapa (rede lenta ou bloqueada), a lista continua valendo: avisa em vez de
  // deixar um quadrado cinza.
  let carregou = false;
  let falhas = 0;
  camada.on("tileload", () => (carregou = true));
  camada.on("tileerror", () => {
    falhas += 1;
    if (falhas >= 4 && !carregou && !alvo.querySelector(".mapa__aviso")) {
      const aviso = document.createElement("p");
      aviso.className = "mapa__aviso";
      aviso.textContent = "Não foi possível carregar as ruas agora. A lista abaixo continua valendo.";
      alvo.append(aviso);
    }
  });

  const pontos = [];
  let pinoVoce = null;

  function rotuloVoce(precisao) {
    return Number.isFinite(precisao) && precisao >= 1 ? `Você (±${Math.round(precisao)} m)` : "Você";
  }

  function pino(lat, lon, { voce, rotulo, precisao }) {
    const marcador = L.marker([lat, lon], {
      icon: L.divIcon({
        className: voce ? "mapa__voce" : "mapa__centro",
        html: "<span></span>",
        iconSize: [22, 22],
      }),
      keyboard: false,
      // "Você" fica acima de tudo; o centro da cidade fica abaixo dos pinos das delegacias.
      zIndexOffset: voce ? 1000 : -500,
    }).addTo(mapa);
    marcador.bindTooltip(escapar(rotulo), {
      permanent: true,
      direction: "bottom",
      offset: [0, 10],
      className: "mapa__rotulo",
    });
    if (voce && Number.isFinite(precisao) && precisao >= 20) {
      // Faixa em que a posição pode estar de fato; some quando o GPS está bem preciso.
      const area = L.circle([lat, lon], {
        radius: precisao,
        className: "mapa__precisao",
        interactive: false,
      }).addTo(mapa);
      marcador.on("remove", () => area.remove());
    }
    return marcador;
  }

  if (origem) {
    const voce = origem.rotulo === "você";
    const marcador = pino(origem.lat, origem.lon, {
      voce,
      precisao: origem.precisao,
      rotulo: voce ? rotuloVoce(origem.precisao) : rotuloCentro(origem.rotulo),
    });
    if (voce) pinoVoce = marcador;
    pontos.push([origem.lat, origem.lon]);
  }

  const marcadores = new Map(); // índice do serviço -> marcador do grupo
  for (const grupo of agruparPorPonto(servicos)) {
    const numeros = grupo.itens.map((i) => i.indice + 1).join("·");
    const especial = grupo.itens.some((i) => i.servico.tipo !== "delegacia_comum");
    const largo = grupo.itens.length > 1;
    const marcador = L.marker([grupo.lat, grupo.lon], {
      title: grupo.itens.map((i) => i.servico.nome).join(" / "),
      icon: L.divIcon({
        className: `mapa__pino${especial ? " mapa__pino--deam" : ""}${largo ? " mapa__pino--grupo" : ""}`,
        html: `<span>${numeros}</span>`,
        iconSize: largo ? [44, 30] : [30, 30],
        iconAnchor: largo ? [22, 15] : [15, 15],
      }),
      zIndexOffset: 500,
    }).addTo(mapa);
    marcador.bindPopup(
      grupo.itens
        .map((i) => `<strong>${i.indice + 1}. ${escapar(i.servico.nome)}</strong><br>${escapar(i.servico.endereco || "")}`)
        .join("<hr>"),
    );
    marcador.on("click", () => aoSelecionar?.(grupo.itens[0].indice));
    grupo.itens.forEach((i) => marcadores.set(i.indice, marcador));
    pontos.push([grupo.lat, grupo.lon]);
  }

  function enquadrar() {
    if (pontos.length) mapa.fitBounds(pontos, { padding: [36, 36], maxZoom: 15 });
    else mapa.setView([-15.79, -47.88], 4);
  }

  // O mapa nasce dentro de um painel que acabou de aparecer: espera o tamanho real antes de
  // enquadrar, senão os pinos saem fora de lugar e as imagens só chegam depois.
  mapa.setView(pontos[0] || [-15.79, -47.88], 12, { animate: false });
  let vivo = true;
  requestAnimationFrame(() => {
    if (!vivo) return; // o mapa foi fechado (ou trocado pelo 3D) antes do primeiro quadro
    mapa.invalidateSize();
    enquadrar();
  });
  const observador = new ResizeObserver(() => vivo && mapa.invalidateSize());
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
      pinoVoce = pino(coords.latitude, coords.longitude, {
        voce: true,
        precisao: coords.accuracy,
        rotulo: rotuloVoce(coords.accuracy),
      });
      mapa.fitBounds([...pontos, [coords.latitude, coords.longitude]], { padding: [36, 36], maxZoom: 16 });
      return true;
    } catch {
      return false;
    }
  }

  function focar(indice) {
    const marcador = marcadores.get(indice);
    if (!marcador) return;
    mapa.setView(marcador.getLatLng(), Math.max(mapa.getZoom(), 15), { animate: true });
    marcador.openPopup();
  }

  return {
    destruir: () => {
      vivo = false;
      observador.disconnect();
      // Zoom animado em andamento estoura 250 ms depois do remove(); o Leaflet não o cancela.
      mapa.stop();
      mapa._animatingZoom = false;
      mapa.remove();
    },
    marcarVoce,
    focar,
  };
}
