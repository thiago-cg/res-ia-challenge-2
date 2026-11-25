/**
 * Botão de pânico: tela com ligação ao 190, saída rápida e um ponto de encaixe para os áudios.
 *
 * Os áudios de apoio são feitos por outra equipe. Este módulo só organiza a tela e avisa quando
 * ela abre ou fecha, por dois eventos no `document`:
 *
 *   zelia:panico:abrir   detail = { slot }   -> monte os controles dentro de `slot`
 *   zelia:panico:fechar  detail = {}         -> pare qualquer áudio e solte os recursos
 *
 * O `slot` fica escondido enquanto estiver vazio e é esvaziado ao fechar, então nenhum controle
 * antigo sobra na tela. Nada daqui guarda dados nem fala com a rede.
 */

import { SAIDA_RAPIDA_URL } from "./delegacias.js";

export const EVENTO_ABRIR = "zelia:panico:abrir";
export const EVENTO_FECHAR = "zelia:panico:fechar";

export function criarPainelPanico({
  dialogo,
  slot,
  sair,
  abrirDialogo,
  fecharDialogo,
  anunciar = () => {},
  emitir = () => {},
  irPara = (url) => window.location.replace(url),
}) {
  let aberto = false;

  function encerrar() {
    if (!aberto) return;
    aberto = false;
    emitir(EVENTO_FECHAR, {});
    slot.replaceChildren();
    slot.hidden = true;
  }

  // Fechar de qualquer jeito (X, Esc, toque fora) também avisa quem toca áudio.
  dialogo.addEventListener("close", encerrar);

  sair.addEventListener("click", () => {
    encerrar();
    fecharDialogo(dialogo);
    irPara(SAIDA_RAPIDA_URL);
  });

  return {
    abrir() {
      aberto = true;
      slot.replaceChildren();
      slot.hidden = true;
      abrirDialogo(dialogo);
      emitir(EVENTO_ABRIR, { slot });
      slot.hidden = slot.childElementCount === 0;
      anunciar("Botão de pânico aberto. Em perigo agora, ligue 190.");
    },
  };
}
