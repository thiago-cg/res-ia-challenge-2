/**
 * Permissão de localização, dentro da tela de Privacidade.
 *
 * Mostra se o navegador já permite a localização e deixa a pessoa pedir a permissão por aqui.
 * A posição lida para disparar o pedido é descartada na hora: nada é guardado nem enviado.
 * Um site não consegue desfazer uma permissão já dada; para isso, só as configurações do
 * navegador, e a tela diz isso.
 */

const TEXTOS = {
  granted: {
    estado: "Permitida neste navegador",
    nota: "Usada só para achar as delegacias perto de você, e só quando você toca em “Usar minha localização”. Para desativar, use as configurações do site no navegador.",
    pedir: false,
  },
  prompt: {
    estado: "Ainda não permitida",
    nota: "Usada só para achar as delegacias perto de você. Fica no aparelho: não é guardada nem compartilhada. Você também pode buscar pela cidade, sem permitir nada.",
    pedir: true,
  },
  denied: {
    estado: "Bloqueada neste navegador",
    nota: "Para permitir, abra as configurações do site no navegador. Enquanto isso, busque pela cidade ou região.",
    pedir: false,
  },
  unknown: {
    estado: "Pergunta ao usar",
    nota: "O navegador vai perguntar quando você tocar em “Usar minha localização”. Fica no aparelho: não é guardada nem compartilhada.",
    pedir: true,
  },
  unsupported: {
    estado: "Indisponível neste aparelho",
    nota: "Este navegador não oferece localização. Busque pela cidade ou região.",
    pedir: false,
  },
};

/** Traduz o estado do navegador para uma das chaves de TEXTOS. */
export function classificarPermissao(estado, temGeolocalizacao = true) {
  if (!temGeolocalizacao) return "unsupported";
  return estado in TEXTOS ? estado : "unknown";
}

export function criarPermissaoLocalizacao({
  estado,
  botao,
  nota,
  dialogo,
  navegador = globalThis.navigator,
}) {
  if (!estado || !botao || !nota) return { atualizar() {} };
  const temGeo = Boolean(navegador && "geolocation" in navegador);
  let consulta = null;
  let ultimo = "unknown";

  function mostrar(chave) {
    ultimo = chave;
    const t = TEXTOS[chave];
    estado.textContent = t.estado;
    nota.textContent = t.nota;
    botao.hidden = !t.pedir;
    botao.disabled = false;
  }

  async function atualizar() {
    if (!temGeo) return mostrar("unsupported");
    try {
      consulta = consulta || (await navegador.permissions.query({ name: "geolocation" }));
      consulta.onchange = () => mostrar(classificarPermissao(consulta.state, temGeo));
      mostrar(classificarPermissao(consulta.state, temGeo));
    } catch {
      // Safari antigo não tem a Permissions API para localização.
      mostrar(ultimo === "granted" ? "granted" : "unknown");
    }
  }

  botao.addEventListener("click", () => {
    if (!temGeo) return;
    botao.disabled = true;
    estado.textContent = "Aguardando sua resposta…";
    navegador.geolocation.getCurrentPosition(
      () => mostrar("granted"), // a posição é ignorada de propósito
      (erro) => {
        if (erro && erro.code === 1) mostrar("denied");
        else mostrar(ultimo === "denied" ? "denied" : "unknown");
      },
      { enableHighAccuracy: false, timeout: 10000, maximumAge: 600000 },
    );
  });

  // Reconsulta ao abrir a tela: a pessoa pode ter mudado a permissão no navegador.
  if (dialogo) {
    new MutationObserver(() => dialogo.open && atualizar()).observe(dialogo, {
      attributes: true,
      attributeFilter: ["open"],
    });
  }
  atualizar();
  return { atualizar };
}
