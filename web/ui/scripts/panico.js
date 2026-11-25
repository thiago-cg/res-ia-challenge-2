/**
 * Botão de pânico: tela com ligação ao 190, saída rápida e um ponto de encaixe para os áudios.
 *
 * Os áudios de apoio são feitos por outra equipe. Este módulo só organiza a tela e avisa quando
 * ela abre ou fecha, por dois eventos no `document`:
 *
 *   zelia:panico:abrir   detail = { slot }   -> monte os controles dentro de `slot`
 *   zelia:panico:fechar  detail = {}         -> pare qualquer áudio e solte os recursos
 *   zelia:panico:audio   detail = { acao, assumir(), aoTerminar() }
 *       Disparado quando a pessoa toca no microfone. `acao` é "tocar" ou "parar".
 *       Quem reproduz o áudio chama `assumir()` (síncrono, dentro do ouvinte) para dizer
 *       "eu cuido disso"; ao acabar a fala, chama `aoTerminar()`. Se ninguém assumir, a tela
 *       avisa que os áudios ainda não estão disponíveis.
 *
 * O `slot` fica escondido enquanto estiver vazio e é esvaziado ao fechar, então nenhum controle
 * antigo sobra na tela. Nada daqui guarda dados nem fala com a rede.
 */

import { SAIDA_RAPIDA_URL } from "./delegacias.js";

export const EVENTO_ABRIR = "zelia:panico:abrir";
export const EVENTO_FECHAR = "zelia:panico:fechar";
export const EVENTO_AUDIO = "zelia:panico:audio";

export const TEXTO_TOCAR = "Reproduzir áudio de apoio";
export const TEXTO_PARAR = "Parar áudio";
export const AVISO_SEM_AUDIO = "Os áudios de apoio ainda não estão disponíveis. Em perigo agora, ligue 190.";

export function criarPainelPanico({
  dialogo,
  slot,
  sair,
  microfone = null,
  microfoneTexto = null,
  aviso = null,
  abrirDialogo,
  fecharDialogo,
  anunciar = () => {},
  emitir = () => {},
  irPara = (url) => window.location.replace(url),
}) {
  let aberto = false;
  let tocando = false;

  function mostrarEstado() {
    if (!microfone) return;
    microfone.setAttribute("aria-pressed", String(tocando));
    if (microfoneTexto) microfoneTexto.textContent = tocando ? TEXTO_PARAR : TEXTO_TOCAR;
  }

  function mostrarAviso(texto) {
    if (!aviso) return;
    aviso.textContent = texto;
    aviso.hidden = !texto;
  }

  function encerrar() {
    if (!aberto) return;
    aberto = false;
    if (tocando) emitir(EVENTO_AUDIO, { acao: "parar", assumir() {}, aoTerminar() {} });
    tocando = false;
    mostrarEstado();
    mostrarAviso("");
    emitir(EVENTO_FECHAR, {});
    slot.replaceChildren();
    slot.hidden = true;
  }

  // Fechar de qualquer jeito (X, Esc, toque fora) também avisa quem toca áudio.
  dialogo.addEventListener("close", encerrar);

  microfone?.addEventListener("click", () => {
    mostrarAviso("");
    if (tocando) {
      tocando = false;
      mostrarEstado();
      emitir(EVENTO_AUDIO, { acao: "parar", assumir() {}, aoTerminar() {} });
      return;
    }
    let assumido = false;
    emitir(EVENTO_AUDIO, {
      acao: "tocar",
      assumir() {
        assumido = true;
      },
      aoTerminar() {
        tocando = false;
        mostrarEstado();
      },
    });
    if (assumido) {
      tocando = true;
      mostrarEstado();
      anunciar("Áudio de apoio tocando.");
    } else {
      mostrarAviso(AVISO_SEM_AUDIO);
    }
  });

  sair.addEventListener("click", () => {
    encerrar();
    fecharDialogo(dialogo);
    irPara(SAIDA_RAPIDA_URL);
  });

  return {
    abrir() {
      aberto = true;
      tocando = false;
      mostrarEstado();
      mostrarAviso("");
      slot.replaceChildren();
      slot.hidden = true;
      abrirDialogo(dialogo);
      emitir(EVENTO_ABRIR, { slot });
      slot.hidden = slot.childElementCount === 0;
      anunciar("Botão de pânico aberto. Em perigo agora, ligue 190.");
    },
  };
}
