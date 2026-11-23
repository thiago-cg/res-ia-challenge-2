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

/**
 * Desenha o mapa em `alvo`. `origem` ({lat, lon, rotulo}) pode ser null.
 * Devolve uma função que destrói o mapa.
 */
export async function mostrarMapa(alvo, { servicos, origem }) {
  const L = await carregarLeaflet();
  alvo.innerHTML = "";
  const mapa = L.map(alvo, { zoomControl: true, attributionControl: true, scrollWheelZoom: false });
  L.tileLayer(TILES_URL, { maxZoom: 18, attribution: ATRIBUICAO, referrerPolicy: "no-referrer" }).addTo(mapa);

  const pontos = [];
  if (origem) {
    const voce = L.marker([origem.lat, origem.lon], {
      icon: L.divIcon({ className: "mapa__voce", html: "<span></span>", iconSize: [18, 18] }),
      keyboard: false,
    }).addTo(mapa);
    voce.bindTooltip(origem.rotulo === "você" ? "Você" : escapar(origem.rotulo));
    pontos.push([origem.lat, origem.lon]);
  }
  servicos.forEach((s, i) => {
    const deam = s.tipo === "deam";
    L.marker([s.latitude, s.longitude], {
      title: s.nome,
      icon: L.divIcon({
        className: `mapa__pino${deam ? " mapa__pino--deam" : ""}`,
        html: `<span>${i + 1}</span>`,
        iconSize: [30, 30],
        iconAnchor: [15, 15],
      }),
    })
      .addTo(mapa)
      .bindPopup(`<strong>${escapar(s.nome)}</strong><br>${escapar(s.endereco || "")}`);
    pontos.push([s.latitude, s.longitude]);
  });
  if (pontos.length) mapa.fitBounds(pontos, { padding: [28, 28], maxZoom: 15 });
  else mapa.setView([-15.79, -47.88], 4);
  return () => mapa.remove();
}
