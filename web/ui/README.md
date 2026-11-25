# Interface do chatbot — ZELIA

Interface visual da funcionalidade de chatbot, construída sobre o design system
extraído do manual de marca. Sem framework, sem build e sem requisição externa em
tempo de execução: HTML, CSS e JavaScript servidos como arquivos estáticos.

- **Design system:** [`docs/design-system.md`](../../docs/design-system.md)
- **Plano da interface:** [`docs/11-interface-chatbot.md`](../../docs/11-interface-chatbot.md)
- **API:** `POST /chat`, `GET /health`, `POST /services/nearby`

## Rodar

Pela própria API (recomendado, mesma origem):

```powershell
uv run uvicorn src.api.main:app --no-access-log
# http://localhost:8000/app/
```

Arquivos estáticos isolados (modo demonstração se a API não estiver em `:8000`):

```powershell
python -m http.server 5500 -d web/ui
# http://localhost:5500/
```

## Parâmetros de URL

| Parâmetro | Efeito |
| --- | --- |
| `?demo=1` | Força o modo demonstração, com respostas de exemplo |
| `?exemplo=medida` | Abre uma conversa de exemplo (medida protetiva) |
| `?exemplo=lei` | Abre a conversa sobre a Lei Maria da Penha |
| `?exemplo=denuncia` | Abre a conversa sobre prazo para denunciar |
| `?exemplo=emergencia` | Abre o bloco de emergência |
| `?exemplo=abstencao` | Abre o estado de abstenção |
| `?api=http://host:porta` | Aponta a interface para outra API |

## Estrutura

```
web/ui/
├── index.html            estrutura, sprite de ícones e diálogos
├── styles/
│   ├── fonts.css         @font-face locais (latin + latin-ext)
│   ├── tokens.css        tokens do design system
│   └── app.css           layout e componentes
├── scripts/
│   ├── app.js            estado, eventos e renderização
│   ├── delegacias.js     painel "Delegacias perto de você" (cartões + mapa de ruas opcional)
│   ├── api.js            cliente /chat e /health com timeout
│   ├── demo.js           respostas de exemplo do contrato
│   └── markdown.js       markdown mínimo e seguro (escapa antes de formatar)
└── assets/
    ├── brand/            kit v1.0: símbolo, wordmark, ícone, favicon (SVG),
    │                     PNGs do ícone (48–1024) e LEIA-ME com as regras de uso
    └── fonts/            Afacad Flux e Newsreader Italic (woff2, SIL OFL 1.1)
```

## Comportamento

- **Modo real:** usa a mesma origem quando servida em `/app`; fora disso, tenta
  `http://localhost:8000` (ou o valor de `?api=`).
- **Modo demonstração:** ativado quando a API não responde (falha de rede) ou por
  `?demo=1`. A faixa superior permanece visível; as respostas são exemplos do
  contrato, não orientação jurídica.
- **Saúde:** `/health` é consultado uma vez, com timeout de 10 s. `degraded`
  aparece como "Serviço parcialmente disponível"; resposta lenta ou inválida
  aparece como "Status indisponível", sem derrubar a conversa.
- **Erro de chat:** cartão com "Tentar de novo" e "Ligar 190"; a pergunta da
  usuária permanece no histórico.
- **Privacidade:** histórico **desligado** por padrão. Quando ligado, fica em
  `localStorage` deste aparelho; "Apagar conversa" exige confirmação em dois toques.
- **Título da aba:** fixo em "Zelia · Organização e informação". Nunca mostra o
  assunto da conversa.
- **Acessibilidade:** `role="log"` com `aria-live="polite"`, foco visível, alvos
  ≥ 44 px, contraste AA/AAA, `prefers-reduced-motion` respeitado.

## Delegacias perto de você

Botão **Delegacias** no topo (e cartão no painel lateral). A usuária escolhe
"Usar minha localização" ou informa UF e cidade; a interface chama
`POST /services/nearby` e mostra a DEAM mais próxima, as delegacias por
distância, telefone, horário e "Como chegar".

- **Mapa de ruas opcional.** A lista de cartões funciona sem terceiros. O mapa
  (Leaflet, servido por `web/ui/vendor/leaflet/`) só é carregado depois que a
  usuária toca em "Abrir o mapa", com aviso na tela: os blocos de imagem vêm do
  OpenStreetMap, que vê a região mostrada e o IP do aparelho. A posição exata
  nunca é enviada. Pino "Você" com GPS; na busca por cidade, o centro da cidade
  e o botão "Marcar onde estou" (localização usada só no navegador). O outro link
  que sai do app é o "Como chegar", só com o destino.
- **Localização:** pedida só ao toque, arredondada a 3 casas (~110 m), enviada
  por POST, nunca gravada (storage, URL, histórico) e apagada ao fechar o painel.
- **Busca por cidade:** a API tem os 5.570 municípios do IBGE com coordenada
  (`data/seed/municipios_br.csv`) e mede a distância a partir do centro da cidade
  escolhida (`referencia` na resposta). Cidade fora da lista, como regiões
  administrativas do DF, mostra o estado com aviso.
- **Dados de delegacias:** `scripts/import_osm_police.py` importa do OpenStreetMap
  (ODbL; a tela atribui a fonte quando exibe esses dados) e nunca sobrescreve as
  linhas curadas à mão.
- **Aproximada:** quando `coordenada_verificada` é falso, o cartão avisa para
  confirmar o endereço por telefone.
- **Modo demonstração:** não inventa delegacias; pede a API conectada.
- **Sair rápido:** apaga o resultado e troca a aba por um site neutro.

## Notas de implementação

- Nenhum dado da API entra no HTML sem escape: `markdown.js` escapa e depois
  aplica um subconjunto de marcações; URLs de fontes são validadas (`http`/`https`).
- As fontes são locais (licença SIL Open Font License 1.1), então a interface não
  faz requisição a terceiros.
- Não há dependências de build nem `node_modules`. Editar e recarregar.

## Menu e botão de pânico

- Barra do topo (ícones): **SOS**, Privacidade e Fontes. Delegacias fica só na tela principal
  (cartão da lateral; no celular, também um atalho na abertura).
- **SOS** abre `#dialogo-panico`: "Ligar 190" (`tel:190`), "Sair rápido" (fecha e vai para uma
  página neutra) e o espaço `#panico-audios` para os áudios de apoio.
- Os áudios são de outra equipe. Para plugar, escute dois eventos no `document`:
  - `zelia:panico:abrir` (`detail.slot`): monte os controles dentro de `slot`;
  - `zelia:panico:fechar`: pare o áudio e solte os recursos.
  O `slot` fica escondido enquanto vazio e é esvaziado ao fechar. O módulo é `scripts/panico.js`.
- Cor de alerta própria: `--cor-panico` (só no SOS).
- Pasta segura: ainda não implementada (próximo patch); o lugar previsto é a barra do topo.

## Mapa 3D (opcional)

- No painel de delegacias, depois de abrir o mapa, o botão **Ver em 3D** troca o Leaflet por
  MapLibre GL (mapa inclinado, prédios em 3D) com colunas do deck.gl sobre cada delegacia
  (DEAM mais alta e azul). **Voltar ao mapa 2D** desfaz.
- `scripts/mapa3d.js` tem a mesma interface de `scripts/mapa.js` (`destruir`, `marcarVoce`, `focar`)
  e só é importado quando a usuária toca no botão. Sem WebGL, o botão nem aparece.
- Bibliotecas no próprio servidor: `vendor/maplibre/` (MapLibre GL 5.x, BSD) e `vendor/deckgl/`
  (deck.gl 9.x, MIT; bundle enxuto com `MapboxOverlay`, `ColumnLayer` e `ScatterplotLayer`).
  Para regenerar o bundle: `npm i deck.gl@9 esbuild` e, em uma pasta com `entrada.js`,
  `npx esbuild entrada.js --bundle --minify --format=iife --target=es2020 --outfile=deckgl.min.js`.
- Único terceiro: os blocos vetoriais da OpenFreeMap (`tiles.openfreemap.org`, dados do OpenStreetMap).
  A tela avisa e a posição da usuária não é enviada. Para trocar de provedor, mude `ESTILO_URL`.

## Menu e microfone do SOS (atualização)

- Topo: logo, **SOS** e **menu (☰)**, em qualquer largura. O menu é uma gaveta com **Privacidade**
  e **Fontes e transparência**; não tem Delegacias nem Data do fato. Delegacias fica na tela
  principal (botão na abertura da conversa); a data do fato continua no chip junto ao campo de texto.
- **Privacidade** inclui a **permissão de localização** (`scripts/localizacao.js`): mostra o estado
  (permitida, bloqueada, a perguntar), deixa pedir a permissão e explica que, para desativar, é
  nas configurações do navegador. A posição lida para disparar o pedido é descartada.
- O SOS tem um botão de **microfone** (`#panico-mic`) para reproduzir o áudio de apoio. Contrato com a
  equipe dos áudios, evento no `document`:

  ```js
  document.addEventListener("zelia:panico:audio", (e) => {
    const { acao, assumir, aoTerminar } = e.detail; // acao: "tocar" | "parar"
    if (acao === "tocar") {
      assumir();            // obrigatório, síncrono: "eu cuido deste áudio"
      tocarAudio().then(aoTerminar); // ao acabar, o botão volta ao estado inicial
    } else {
      pararAudio();
    }
  });
  ```

  Sem ninguém chamando `assumir()`, a tela mostra que os áudios ainda não estão disponíveis e
  lembra do 190. Fechar a tela do SOS também dispara `acao: "parar"` se houver áudio tocando.

## Pasta segura (`#dialogo-cofre`)

Guarda conversas trancadas por PIN, só neste aparelho (IndexedDB), com dia e hora, e gera um
relatório (HTML para imprimir/salvar em PDF).

- `cofre-cripto.js`: WebCrypto. PIN → PBKDF2-SHA-256 (600 mil voltas) → AES-256-GCM protege a chave
  privada ECDH P-256. A chave pública fica em claro, então **guardar não pede PIN**; **ler pede**.
- `cofre.js`: lógica sem DOM (criar, arquivar, desbloquear, espera após 5 PINs errados, trocar PIN).
- `armazem-idb.js`: persistência; `relatorio.js`: relatório com hash SHA-256 e texto escapado.
- `pasta-segura.js`: tela. Tranca ao fechar o diálogo e após 5 min sem uso.
- Em **Apagar conversa**, se a Pasta existe a conversa é guardada antes de apagar; se guardar falhar,
  **não apaga**. Nada é enviado à rede.

Limites: não recupera PIN esquecido; PIN curto é mais fraco que frase longa contra quem copiar o
banco do aparelho; o relatório é registro pessoal, não prova autenticada.
