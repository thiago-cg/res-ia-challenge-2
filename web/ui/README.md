# Interface do chatbot — ZELIA

Interface visual da funcionalidade de chatbot, construída sobre o design system
extraído do manual de marca. Sem framework, sem build e sem requisição externa em
tempo de execução: HTML, CSS e JavaScript servidos como arquivos estáticos.

- **Design system:** [`docs/design-system.md`](../../docs/design-system.md)
- **Plano da interface:** [`docs/11-interface-chatbot.md`](../../docs/11-interface-chatbot.md)
- **API:** `POST /chat`, `GET /health`

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

## Notas de implementação

- Nenhum dado da API entra no HTML sem escape: `markdown.js` escapa e depois
  aplica um subconjunto de marcações; URLs de fontes são validadas (`http`/`https`).
- As fontes são locais (licença SIL Open Font License 1.1), então a interface não
  faz requisição a terceiros.
- Não há dependências de build nem `node_modules`. Editar e recarregar.
