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
│   ├── delegacias.js     painel "Delegacias perto de você" (esquema SVG + cartões)
│   ├── api.js            cliente /chat e /health com timeout
│   ├── demo.js           respostas de exemplo do contrato
│   └── markdown.js       markdown mínimo e seguro (escapa antes de formatar)
└── assets/
    ├── brand/            símbolo, wordmark, ícone e favicon (SVG)
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

- **Sem mapa de terceiros.** O resultado é um esquema de distância e direção
  desenhado em SVG no navegador (norte para cima), e não um mapa de ruas: tiles
  do OpenStreetMap ou do Google revelariam a região e o IP a terceiros. O único
  link que sai do app é o "Como chegar", aberto por toque, só com o destino.
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
