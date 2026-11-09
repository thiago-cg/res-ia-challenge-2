# 11 — Interface do chatbot (plano)

**Status:** implementado · 2026-11-09
**Base de marca:** [`design-system.md`](design-system.md) (Manual de Identidade Visual ZELIA v1.0)
**Implementação:** [`web/ui/`](../web/ui/) · **API:** `POST /chat`, `GET /health`

Este documento planeja a interface visual da funcionalidade de chatbot antes do código:
o que aparece, em que ordem, com qual comportamento e por quê. A seção 15 fecha o plano
em tarefas e critérios de aceite.

---

## 1. Objetivo

Dar à funcionalidade de chatbot uma interface própria — não um chat genérico — que:

1. **mostre a promessa do produto**: resposta em linguagem simples **com a fonte na mão**;
2. **trate risco imediato como interrupção**, não como mais uma mensagem;
3. **pareça uma ferramenta de organização**, não um app de denúncia (discrição);
4. **reduza carga cognitiva**: uma decisão por vez, nada de menus paralelos;
5. **seja operável em crise**: alvos grandes, teclado, leitor de tela, pouco texto por tela.

Fora do escopo desta entrega: autenticação, voz, upload de documentos, mapa de serviços,
integração com WhatsApp, tema escuro completo.

---

## 2. Princípios de interface

| Princípio | Consequência concreta |
| --- | --- |
| **A resposta é o produto** | A conversa ocupa o centro; o resto (contexto, privacidade) vive na coluna lateral. |
| **Fonte sempre visível** | Toda resposta traz o cartão "Fontes verificadas" aberto por padrão. |
| **Limite declarado** | Aviso legal e data da base aparecem em toda resposta, em uma linha discreta. |
| **Risco interrompe** | O bloco de emergência substitui a bolha comum e vem antes de qualquer outra ação. |
| **Nada de beco sem saída** | Abstenção, erro e offline sempre oferecem um próximo passo (reformular, 180, tentar de novo). |
| **Discrição por padrão** | Título neutro, histórico opcional, sem nome, sem foto, sem notificação com prévia. |
| **Sem infantilizar** | Sem emoji em conteúdo sensível, sem diminutivo, sem "calma, vai ficar tudo bem". |

---

## 3. Contexto de uso

A pessoa pode estar em crise, com pressa, em um aparelho compartilhado, com pouca
familiaridade digital e medo de exposição. Isso define:

- **uma coluna de leitura curta** (760 px) — olho não varre 1400 px de texto;
- **composer sempre visível** — não é preciso "abrir o chat";
- **respostas escaneáveis** — prosa curta + blocos com título;
- **alvos ≥ 44 px** e foco visível;
- **nada de conteúdo sensível fora da conversa** (título, notificação, URL);
- **saída rápida** — o botão "Continuar depois" e o "Limpar conversa" sempre alcançáveis.

---

## 4. Mapa de telas e estados

Aplicação de página única, sem rotas. A conversa é o estado; as sobreposições são diálogos.

| Tela / estado | Quando aparece | Conteúdo principal |
| --- | --- | --- |
| **Abertura** (thread vazia) | Primeiro acesso, ou após limpar | Título editorial, promessa, chip de privacidade, 3 perguntas de exemplo |
| **Conversa** | ≥ 1 mensagem | Histórico, composer, ações rápidas |
| **Carregando** | Requisição em curso | Indicador "Zelia está organizando as fontes…" + esqueleto discreto |
| **Resposta jurídica** | `emergencia=false`, `abstencao=false` | Prosa, fontes, próximos passos, encaminhamentos, confiança, aviso |
| **Emergência** | `emergencia=true` | Bloco azul com 190/180/100/197, passos de segurança, "continuar depois" |
| **Abstenção** | `abstencao=true` | Explicação do limite, motivo, encaminhamento, "reformular pergunta" |
| **Erro de serviço** | Falha de rede/5xx | Mensagem fixa + "Tentar de novo" + 190 |
| **Offline / demo** | API inacessível na abertura | Faixa "Modo demonstração" + respostas de exemplo |
| **Serviço degradado** | `health.status=degraded` | Selo na lateral: "Serviço parcialmente disponível" |
| **Privacidade** | Diálogo | Histórico local, prévia oculta, apagar dados |
| **Fontes e transparência** | Diálogo | O que a base cobre, data de atualização, aviso legal |
| **Contexto (mobile)** | Botão "Contexto" | Painel deslizante com a coluna lateral |

---

## 5. Fluxos

### F1 — Pergunta jurídica (J2 do escopo)

1. A pessoa toca em uma pergunta de exemplo **ou** escreve no composer e envia.
2. A pergunta vira bolha lavanda à direita; o composer limpa e mantém o foco.
3. Surge o indicador de digitação (com `aria-live="polite"`), com rótulo textual.
4. A resposta entra em três camadas: **prosa** (bolha areia) → **fontes** (cartão branco,
   aberto) → **próximos passos e ajuda** (cartões brancos).
5. Sob a resposta: nível de confiança, data da base, aviso legal e chips
   "Ver possibilidades" / "Explicar de outro jeito".
6. O foco permanece no composer; o leitor de tela anuncia o início da nova resposta.

### F2 — Risco imediato (J1)

1. A pergunta é enviada normalmente.
2. A resposta volta com `emergencia=true`; a interface **não** renderiza bolha comum.
3. Entra o bloco de emergência: título, telefones como botões `tel:`, passos de segurança
   e a pergunta "Você quer que eu explique os direitos depois?".
4. O bloco recebe foco de leitura (`tabindex="-1"`) e é anunciado por inteiro.
5. Abaixo, "Onde procurar ajuda" com os encaminhamentos e um "Passo a passo" recolhível.

### F3 — Fora do corpus (J4)

1. `abstencao=true` → cartão neutro com o motivo e o limite explícito.
2. Ações: "Reformular a pergunta" (foca o composer com a pergunta atual selecionada),
   "Falar com a Defensoria" e "Ligar 180".
3. Nunca aparece "não sei" sozinho; sempre há para onde ir.

### F4 — Falha de serviço

1. A mensagem da usuária permanece no histórico.
2. Cartão de erro com texto fixo e "Tentar de novo" (reenvia a mesma pergunta).
3. Se o erro for de rede no primeiro carregamento, a interface entra em modo demonstração
   e avisa na faixa superior.

### F5 — Privacidade

1. Botão "Privacidade" no cabeçalho abre o diálogo.
2. "Histórico neste aparelho" (padrão desligado), "Prévia em notificações" (sempre oculta,
   bloqueado), "Acesso por voz" (desativado, "em breve").
3. "Apagar conversa deste aparelho" pede confirmação e limpa mensagens + armazenamento.

---

## 6. Layout

### Desktop (≥ 1200 px)

```
┌ topo: marca ························ status · privacidade · fontes ┐
│ ┌──────────── janela de conversa (760) ────────────┐ ┌ contexto ┐ │
│ │ thread (rola)                                    │ │ sobre    │ │
│ │                                                  │ │ data     │ │
│ │                                                  │ │ exemplos │ │
│ │ composer (fixo no rodapé da janela)              │ │ privac.  │ │
│ └──────────────────────────────────────────────────┘ └──────────┘ │
└───────────────────────────────────────────────────────────────────┘
```

- Fundo da página: aveia `#F5F0E7`.
- Janela de conversa: branco quente `#FFFDF8`, raio 32, fio 1 px, sem sombra.
- Coluna de contexto: 320 px, cartões de 24 px de raio diretamente sobre aveia.
- Altura: `100dvh`, topo 76 px, conversa rolando por dentro, composer sempre visível.

### Tablet (960–1199 px)

Aside em 288 px; goteira 20 px; janela de conversa ocupa o restante (mín. 560 px).

### Mobile (< 960 px)

Uma coluna; a coluna de contexto vira painel deslizante acionado por "Contexto" no topo.
O composer fica fixo no rodapé da viewport, com `env(safe-area-inset-bottom)`.
Em < 640 px, margens de 16 px, bolhas até 88%, título display em 36 px.

---

## 7. Inventário de componentes

| Componente | Onde | Estados | Tokens principais |
| --- | --- | --- | --- |
| `topo` | Global | padrão, degradado, demo | `--cor-fundo`, `--borda-fina` |
| `marca` | Topo, abertura | estática, animada (1200 ms) | `--zelia-azul`, `--mov-marca` |
| `selo-status` | Topo, lateral | ok, degradado, offline | `--verde-*`, `--sol-*`, `--nevoa` |
| `botao` | Global | primário, secundário, fantasma, ícone | `--cor-acao`, `--raio-pill` |
| `chip` | Mensagens, filtros | padrão, selecionado, desabilitado | `--raio-pill` |
| `bolha` | Thread | usuária, assistente | `#DCE5FD`, `#EEEADE` |
| `cartao-fontes` | Resposta | aberto, fechado, vazio | `--cor-superficie`, `--raio-lg` |
| `selo-vigencia` | Fonte | vigente, alterado, revogado | `--verde-*`, `--sol-*`, `--nevoa` |
| `passos` | Resposta | lista numerada | `--verde-escuro`, `--zelia-sol` |
| `encaminhamento` | Resposta | com/sem telefone | `--cor-superficie-2` |
| `bloco-emergencia` | Resposta | único | `--zelia-azul`, `#FFFDF8` |
| `cartao-abstencao` | Resposta | único | `--cor-superficie-2` |
| `cartao-erro` | Thread | único | `--cor-superficie-2` |
| `indicador-digitacao` | Thread | animado, reduzido | `--mov-padrao` |
| `composer` | Rodapé | vazio, foco, enviando, limite | `--raio-pill`, `--cor-acao` |
| `dica-privacidade` | Composer | fixo | `--texto-pequeno` |
| `data-do-fato` | Lateral, composer | vazio, definido | `--cor-acao` |
| `dialogo` | Sobreposição | aberto, fechado | `--sombra-2`, `--raio-xl` |
| `painel-contexto` | Mobile | aberto, fechado | `--mov-lento` |
| `faixa-demo` | Topo | visível só em demo | `--zelia-sol-claro` |

---

## 8. Especificação por bloco

### 8.1 Cabeçalho

- Esquerda: tile de 36 px (azul pulso, raio 11, símbolo branco) + wordmark de 22 px de altura.
  O símbolo desenha o traço em 1200 ms na primeira carga e assenta (sem bounce).
- Direita: selo de status ("Base atualizada em 05/11"), botão "Privacidade" (cadeado),
  botão "Fontes" (documento), botão "Contexto" (só < 960 px).
- O cabeçalho não muda com o assunto da conversa. **Título da aba fixo.**

### 8.2 Abertura

Ordem: rótulo caixa alta → título display com trecho em Newsreader itálico → promessa →
chip de privacidade → "Comece por onde for mais fácil" → 3 cartões de pergunta →
nota de rodapé com base legal e aviso.

- Título: **"Entenda o que a lei diz, _no seu tempo._"**
- Promessa: "Informação confiável, em linguagem simples, com a fonte na mão."
- Chip: "Conversa privada · nada aparece em notificações"
- Cada cartão de exemplo tem a pergunta em 15 px/500 e seta à direita; ao clicar, envia.
- Fio de conversa decorativo (curva azul a 8% de opacidade) no canto superior direito,
  `aria-hidden="true"`, desligado em movimento reduzido.

### 8.3 Thread

- `role="log"`, `aria-live="polite"`, `aria-relevant="additions"`, `aria-label="Conversa"`.
- Cada mensagem: `<article>` com autor visível só para a assistente (avatar + "Zelia").
- Distância entre mensagens: 20 px; entre autor e conteúdo: 8 px.
- Ao entrar: opacidade 0→1 e 8 px de deslocamento em 240 ms. Nunca bounce.
- A rolagem acompanha a nova mensagem **apenas** se a pessoa já estava no fim.

### 8.4 Resposta jurídica

1. **Prosa** em bolha areia, 16/24, com negrito para nomes de lei e prazos.
2. **Fontes verificadas** — cartão branco, cabeçalho "Fontes verificadas" + "N referências
   institucionais" + chevron. Aberto por padrão. Cada fonte: citação em 14 px/600,
   texto literal em 14/21, selo de vigência, link "Abrir a fonte oficial ↗".
3. **Próximos passos** — cartão com trilho vertical e pontos de presença; números 1..n.
4. **Onde procurar ajuda** — cartão com uma linha por encaminhamento: ícone, tipo
   legível ("Polícia", "Central de Atendimento à Mulher"), descrição e telefone como link.
5. **Rodapé da resposta** — chip de confiança (alto/médio/baixo), "Base de dd/mm/aaaa" e
   aviso legal em 12 px.
6. **Chips de continuação** — "Ver possibilidades" (rola até os passos),
   "Explicar de outro jeito" (envia "Explique de forma mais simples, por favor.").

Confiança: alto = verde claro; médio = sol claro; baixo = névoa. Sempre com rótulo textual.

### 8.5 Bloco de emergência

- Fundo azul pulso, texto branco quente, raio 24, padding 24.
- Rótulo "RISCO IMEDIATO" em branco 80% + ícone de escudo.
- Título: "Se você está em perigo agora, ligue 190."
- Quatro ações: **190** (branco sobre azul, sólido), **180** (verde escuro `#1F6B57`),
  **100** e **197** (contorno branco). Todas `tel:`.
- Corpo: o texto de emergência da API, preservando as quebras de linha.
- Rodapé: "Você pode continuar depois. A conversa não aparece em notificações."
- Recebe foco ao entrar (`tabindex="-1"`) para leitura imediata.

### 8.6 Abstenção

- Cartão areia clara com ícone de informação.
- Título: "Não encontrei base suficiente para responder com segurança."
- Motivo vindo de `motivo_abstencao`, em 15 px.
- Ações: "Reformular pergunta", "Falar com a Defensoria", "Ligar 180".

### 8.7 Composer

- Pílula de 56 px (cresce até 160), fundo aveia sobre a janela branca, fio 1 px.
- Placeholder: **"Escreva no seu tempo…"**
- Botão de microfone (44 px, desabilitado, `title="Em breve"`), botão enviar circular azul
  de 44 px, desabilitado quando vazio.
- `Enter` envia; `Shift+Enter` quebra linha; contador aparece só a partir de 7500 caracteres.
- Abaixo: cadeado + "Não informe nome, CPF, endereço, telefone ou documentos."
  à esquerda; chip "Data do fato" à direita quando definida.
- Estado de envio: botão vira spinner discreto; composer não bloqueia (a pessoa pode
  continuar lendo).

### 8.8 Coluna de contexto

1. **Sobre esta orientação** — aviso legal, "não informe PII", status dos serviços, data da base.
2. **Data do fato (opcional)** — campo de data; texto de ajuda: "Ela define a versão da lei
   aplicável."; botão "Limpar" quando definida.
3. **Perguntas de exemplo** — 3 botões; envia direto.
4. **Privacidade** — resumo do estado e atalho para o diálogo.
5. Rodapé: "Zelia · Organização e informação" e link para "Fontes e transparência".

### 8.9 Diálogos

- `<dialog>` nativo com `::backdrop` em tinta a 32%.
- Largura 480 px, raio 24, padding 24, cabeçalho com título e botão fechar.
- Privacidade: três linhas com toggle (histórico, prévia bloqueada, voz desativada) e ação
  destrutiva suave.
- Fontes e transparência: o que a base cobre, data de atualização, aviso legal completo,
  link para as fontes oficiais.

---

## 9. Conteúdo e microcopy

| Contexto | Texto |
| --- | --- |
| Título da aba | `Zelia · Organização e informação` |
| Título da abertura | "Entenda o que a lei diz, *no seu tempo.*" |
| Promessa | "Informação confiável, em linguagem simples, com a fonte na mão." |
| Chip de privacidade | "Conversa privada · nada aparece em notificações" |
| Seção de exemplos | "Comece por onde for mais fácil" |
| Placeholder | "Escreva no seu tempo…" |
| Dica de PII | "Não informe nome, CPF, endereço, telefone ou documentos." |
| Carregando | "Zelia está organizando as fontes…" |
| Fontes | "Fontes verificadas" · "2 referências institucionais" |
| Passos | "Próximos passos" |
| Ajuda | "Onde procurar ajuda" |
| Confiança | "Confiança alta" · "Confiança média" · "Confiança baixa" |
| Aviso | "Orientação informativa. Não substitui atendimento jurídico individual." |
| Erro | "Não foi possível falar com o serviço agora. Se você está em perigo, ligue 190." |
| Abstenção | "Não encontrei base suficiente para responder com segurança." |
| Demo | "Modo demonstração · respostas de exemplo" |

Regra de escrita: frases de até 20 palavras em mensagens de estado; nenhuma palavra em
caixa alta fora de rótulo; nenhum ponto de exclamação em conteúdo sensível.

---

## 10. Estados do sistema

| Estado | Sinal visual | Comportamento |
| --- | --- | --- |
| Carregando | Três pontos + rótulo | Composer editável; o envio aguarda a resposta |
| Vazio | Abertura | Composer em foco, sem foco automático em mobile |
| Erro | Cartão areia com ícone | "Tentar de novo" reenvia a última pergunta |
| Offline | Faixa sol claro no topo | Modo demonstração explícito, nunca silencioso |
| Degradado | Selo sol na lateral | Respostas continuam; aviso de base parcial |
| Limite de caracteres | Contador + aviso | Bloqueia acima de 8000, sem perder texto |
| Movimento reduzido | — | Sem traço animado, sem pulso, sem deslocamento |

---

## 11. Acessibilidade

- WCAG 2.2 AA como piso; AAA em texto principal (já garantido pela paleta).
- Foco visível em tudo: anel azul de 2 px com 2 px de afastamento.
- Ordem de tabulação: marca → status → privacidade → fontes → thread → composer → lateral.
- `role="log"` na thread; `aria-live="polite"`; nunca `assertive` para resposta jurídica.
- Emergência é anunciada por inteiro e recebe foco de leitura.
- Botões só com ícone têm `aria-label`; ícones decorativos têm `aria-hidden`.
- Alvos de toque ≥ 44 × 44 px; espaçamento ≥ 8 px.
- Contraste de texto ≥ 4,5:1; estados nunca dependem só de cor.
- `prefers-reduced-motion` respeitado em marca, digitação e entrada de mensagem.
- Zoom de 200% sem perda de conteúdo; nada de texto em imagem.
- Idioma declarado `lang="pt-BR"`; datas em `dd/mm/aaaa`; números de lei por extenso.

---

## 12. Privacidade e discrição

| Decisão | Motivo |
| --- | --- |
| Título fixo "Zelia · Organização e informação" | Aba compartilhada não revela o assunto |
| Histórico **desligado** por padrão | Aparelho compartilhado é o cenário de risco |
| Nenhuma prévia de notificação | Regra do manual; conteúdo sensível nunca em título |
| Sem nome, foto ou conta | Menos dado pessoal; menos exposição |
| `session_id` por aba, não persistido sem histórico | Reduz rastreabilidade |
| Aviso de PII antes do envio | Prevenção, não correção |
| "Apagar conversa" sempre visível | Controle explícito |
| Sem analytics, sem fonte externa | Nenhuma requisição a terceiros |

> **Desvio consciente do manual:** a tela de privacidade ilustrada mostra o histórico
> **ligado**. A interface adota **desligado** por padrão e explica a escolha no diálogo
> ("Por padrão, a conversa fica só nesta aba"). O controle continua disponível e explícito.

---

## 13. Integração com a API

### Contrato usado

```http
POST /chat
{ "session_id": "...", "message": "...", "facts": { "data_fato": "2026-10-01", "uf": "SP" } }
→ { resposta, citacoes[], proximos_passos[], encaminhamentos[], premissas[],
    nivel_confianca, abstencao, motivo_abstencao, emergencia, data_atualizacao_base, aviso_legal }

GET /health
→ { status: "ok" | "degraded", database, qdrant, index_version, last_ingest, data_atualizacao_base }
```

### Mapeamento

| Campo da API | Onde aparece |
| --- | --- |
| `resposta` | Bolha da assistente (markdown mínimo: parágrafos, listas, negrito, itálico) |
| `citacoes[].citacao` | Título da fonte |
| `citacoes[].texto` | Texto literal, 14 px |
| `citacoes[].vigencia` | Selo vigente/alterado/revogado |
| `citacoes[].fonte_url` | "Abrir a fonte oficial" (nova aba, `rel="noopener noreferrer"`) |
| `proximos_passos` | Cartão numerado |
| `encaminhamentos[].tipo` | Rótulo legível + ícone + telefone quando conhecido |
| `premissas` | Recolhível "Premissas desta resposta" |
| `nivel_confianca` | Chip de confiança |
| `abstencao` / `motivo_abstencao` | Cartão de abstenção |
| `emergencia` | Bloco de emergência |
| `data_atualizacao_base` | Rodapé da resposta e coluna de contexto |
| `aviso_legal` | Rodapé da resposta |

### Erros e resiliência

- Timeout de 60 s (mesmo do Streamlit atual); sem retry automático — "Tentar de novo" é ação.
- `4xx`/`5xx` → cartão de erro com o texto fixo; nunca ecoar `detail` da API.
- Falha de rede na abertura → modo demonstração, com respostas de exemplo do contrato.
- `session_id`: `crypto.randomUUID()` por aba; persistido só se o histórico estiver ligado.

### Modo demonstração

Ativado quando a API não responde (falha de rede) ou quando `?demo=1` está na URL.
Se o `/health` apenas demora ou responde de forma inválida, a interface continua no
modo real e mostra "Status indisponível" — uma resposta lenta do health não deve
transformar a conversa em exemplo. O health tem timeout de 10 s (o probe do banco
leva alguns segundos quando o Postgres está fora). Mostra faixa no topo e usa
respostas de exemplo realistas (medida protetiva, Lei Maria da Penha, emergência,
abstenção). **Nunca** se passa por resposta real: a faixa permanece visível.

---

## 14. Arquitetura da implementação

Sem build, sem framework, sem dependência externa. Servido pela própria API.

```
web/ui/
├── index.html            estrutura, símbolos de ícone, fontes
├── styles/
│   ├── fonts.css         @font-face locais (gerado)
│   ├── tokens.css        tokens do design system
│   └── app.css           layout e componentes
├── scripts/
│   ├── app.js            estado, eventos, renderização
│   ├── api.js            cliente /chat e /health
│   ├── demo.js           respostas de exemplo
│   └── markdown.js       markdown mínimo e seguro
└── assets/
    ├── brand/*.svg
    └── fonts/*.woff2
```

- `index.html` monta a estrutura; JS renderiza a thread.
- Texto da API entra sempre escapado; nenhum `innerHTML` com dado bruto.
- Estado em memória; `localStorage` só com o histórico ligado.
- `document.title` fixo.

**Servir:**

```bash
uvicorn src.api.main:app --reload --no-access-log   # API + interface em /app
python -m http.server 5500 -d web/ui                # interface isolada (modo demo)
```

A API monta `web/ui` em `/app` (`StaticFiles`) e redireciona `/` para `/app/`.

---

## 15. Plano de implementação

### Fase 1 — Fundação (design system no código)

- [x] Extrair o manual, documentar em `docs/design-system.md`.
- [x] Vetorizar símbolo, wordmark, ícone e favicon.
- [x] Baixar e servir Afacad Flux e Newsreader localmente.
- [x] `tokens.css` com cor, tipo, espaço, raio, sombra e movimento.

### Fase 2 — Casca e abertura

- [x] Cabeçalho com marca animada (1200 ms, reduzível).
- [x] Janela de conversa, coluna de contexto, responsividade.
- [x] Abertura com título editorial, chip, exemplos e nota legal.

### Fase 3 — Conversa

- [x] Composer (crescimento, Enter/Shift+Enter, limite, dica de PII, data do fato).
- [x] Thread com bolhas, avatar, entrada animada e rolagem condicional.
- [x] Indicador de digitação e anúncio em leitor de tela.

### Fase 4 — Respostas

- [x] Resposta jurídica completa (fontes, passos, ajuda, confiança, aviso).
- [x] Bloco de emergência com telefones.
- [x] Abstenção, erro e "tentar de novo".
- [x] Chips de continuação.

### Fase 5 — Privacidade e integração

- [x] Diálogos de privacidade e de fontes.
- [x] Persistência local opcional + apagar conversa.
- [x] Cliente da API, timeout, health, modo demonstração.
- [x] Montagem em `/app` na API.

### Fase 6 — Verificação

- [x] Revisão visual em 1440, 1024 e 390 px.
- [x] Checklist de acessibilidade (teclado, foco, contraste, leitor de tela).
- [x] `ruff` e `pytest` verdes após a montagem estática.
- [x] Documentação atualizada (`docs/README.md`, `web/ui/README.md`).

### Critérios de aceite

1. A interface abre em `/app` e funciona sem a API (modo demonstração explícito).
2. Toda resposta exibe fonte, vigência, data da base e aviso legal.
3. Emergência aparece como bloco próprio, com 190/180 acionáveis, antes de qualquer outra ação.
4. Abstenção e erro sempre oferecem próximo passo.
5. Nenhuma mensagem sensível aparece no título da aba.
6. Contraste e foco conferidos; teclado percorre toda a interface.
7. Layout íntegro em 1440, 1024 e 390 px.
8. Nenhuma requisição externa em tempo de execução.

---

## 16. Fora de escopo / próximos passos

- Tema escuro (o manual não define; exigiria paleta própria).
- Voz (RF12, fora do MVP).
- Mapa de serviços e geolocalização.
- Múltiplas conversas e histórico entre sessões.
- Internacionalização.
- Testes automatizados de interface (Playwright) — recomendados na fase de produto.
