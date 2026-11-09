# Sistema de design — ZELIA

Extraído do **Manual de Identidade Visual ZELIA v1.0** (novembro de 2026, 14 páginas),
arquivo `zelia_manual_identidade_v1.pdf`. Este documento é a referência de marca e de
interface do projeto: tudo o que a interface do chatbot usa em cor, tipo, espaço,
componente e tom vem daqui.

- **Tokens de execução:** [`web/ui/styles/tokens.css`](../web/ui/styles/tokens.css)
- **Assets de marca:** [`web/ui/assets/brand/`](../web/ui/assets/brand/)
- **Plano da interface:** [`11-interface-chatbot.md`](11-interface-chatbot.md)

---

## 1. Origem e escopo

O manual define uma marca de produto digital para **informação, orientação e rede de apoio**.
Não é uma marca jurídica, nem institucional, nem "de causas": é uma marca de ferramenta
pessoal — próxima, discreta, previsível. A interface do chatbot herda essa posição.

| O manual define | A interface aplica |
| --- | --- |
| Essência e atributos | Tom de voz, densidade, escolhas de interação |
| Símbolo, wordmark e versões | Cabeçalho, avatar, ícone do app, favicon |
| Paleta e contraste | Superfícies, ações, estados, foco |
| Tipografia e hierarquia | Escala real da interface web |
| Sistema visual (fios, janelas, pontos) | Cartões, divisores, indicadores de passo |
| Movimento | Entrada da marca, transições, carregamento |
| Discreção | Título neutro da página, histórico local, sem prévia sensível |

O manual foi desenhado em telas de 960 × 540 pt (16:9). As medidas tipográficas originais
são preservadas aqui como referência de proporção; a escala web está na seção 6.

---

## 2. Essência

**Posicionamento:** *Clareza para seguir no seu próprio ritmo.*

A marca amplia acesso sem ocupar o centro da decisão. A tecnologia cria espaço, aproxima
possibilidades e respeita o ritmo de cada pessoa.

| # | Atributo | Tradução para interface |
| --- | --- | --- |
| 01 | **Humana** | Escuta sem infantilizar. Frases curtas, sem diminutivos, sem exclamação. |
| 02 | **Acolhedora** | Cria espaço sem julgar. Nenhum estado de erro culpa a usuária. |
| 03 | **Confiante** | Orienta com responsabilidade. Fonte sempre visível, limite sempre declarado. |
| 04 | **Expressiva** | Tem presença sem exposição. Cor e movimento com função, nunca decoração gritante. |

**Conceito criativo — Percurso.** O Z deixa de ser ângulo rígido e vira caminho: começa
firme, muda de direção e permanece aberto. Metáfora de autonomia, continuidade e escolhas
possíveis. A frase-manifesto do manual:

> "A marca acompanha o movimento. Nunca determina o destino."

Consequência prática: a interface **não empurra** a usuária para uma decisão. Ela oferece
caminhos, mostra fontes e deixa o próximo passo em aberto ("Ver possibilidades", "Explicar
de outro jeito", "Continuar depois").

---

## 3. Logotipo

### 3.1 Construção

- **Símbolo:** uma linha única, traço de **18 u**, **3 movimentos** (barra de entrada,
  mudança de direção, saída aberta), **1 componente escalável**. Terminais e junções
  arredondados; nada de geometria rígida.
- **Wordmark:** monolinha, mesma espessura relativa do símbolo, com o **ponto solar**
  (Sol) sobre o `i`. Símbolo e nome são uma construção só.
- **Assinatura principal:** símbolo + wordmark, sempre nesta ordem, com o ponto solar
  alinhado à altura das ascendentes.

Proporções extraídas do PDF: símbolo `237,24 × 214,64` (razão 1,105); wordmark
`346,45 × 147,90` (razão 2,342); espessura do wordmark `16,585` para altura de `147,90`
(≈ 11,2% da altura). O ponto solar tem diâmetro `24,1` (≈ 16% da altura do wordmark).

### 3.2 Arquivos oficiais no repositório

| Arquivo | Uso |
| --- | --- |
| [`simbolo-azul.svg`](../web/ui/assets/brand/simbolo-azul.svg) | Avatar, ícone de contexto, marca d'água |
| [`simbolo-branco.svg`](../web/ui/assets/brand/simbolo-branco.svg) | Sobre azul pulso ou tinta |
| [`wordmark-azul.svg`](../web/ui/assets/brand/wordmark-azul.svg) | Assinatura principal em fundos claros |
| [`wordmark-branco.svg`](../web/ui/assets/brand/wordmark-branco.svg) | Assinatura reversa em fundos escuros |
| [`wordmark-tinta.svg`](../web/ui/assets/brand/wordmark-tinta.svg) | Uso monocromático em documentos |
| [`icone-app.svg`](../web/ui/assets/brand/icone-app.svg) | Ícone de aplicativo, 1024 × 1024, raio 232 |
| [`favicon.svg`](../web/ui/assets/brand/favicon.svg) | Favicon (mesma geometria) |

Os SVGs foram vetorizados a partir do PDF original, com os caminhos preservados
(traço arredondado, sem conversão para contorno). O `favicon.svg` é o mesmo desenho do
ícone do app.

### 3.3 Área de proteção e tamanhos

- **Área de proteção:** equivalente à altura do ponto solar em todos os lados
  (`x` no manual). Na prática web, no mínimo **16 px** livres ao redor.
- **Tamanho mínimo digital:** **16 px** (símbolo). Wordmark: **88 px** de largura.
- **Tamanho mínimo impresso:** 5 mm.
- O símbolo é legível de 16 px a grandes formatos sem redesenho.

### 3.4 Versões e usos incorretos

Versões previstas: **principal** (fundos claros), **reversa** (fundos escuros), **símbolo**
(ícone e avatar).

Nunca: distorcer, girar, contornar, aplicar sombra, trocar as cores, usar em baixo contraste.

---

## 4. Cor

### 4.1 Paleta de marca

| Papel | Nome | HEX | RGB | Uso |
| --- | --- | --- | --- | --- |
| Principal | **Azul pulso** | `#2457D6` | 36 87 214 | Marca, navegação, ações |
| Secundária | **Verde folha** | `#2E8B72` | 46 139 114 | Apoio e disponibilidade |
| Destaque | **Sol** | `#F3B83F` | 243 184 63 | **Somente decorativo** |
| Fundo | **Aveia** | `#F5F0E7` | 245 240 231 | Calor e respiro |
| Texto | **Tinta** | `#1E2A3A` | 30 42 58 | Leitura e estrutura |

> **Regra dura:** Sol nunca carrega ação, foco ou texto. Estados sempre combinam
> **cor + ícone + mensagem** — nunca só cor.

### 4.2 Tons de apoio

Extraídos das telas de produto do manual (páginas 12 e 13), para superfícies e estados:

| Nome | HEX | Onde aparece |
| --- | --- | --- |
| Branco quente | `#FFFDF8` | Superfície de leitura, fundo da tela do app |
| Lavanda | `#E3E9FF` | Superfície de marca (cartão da capa, tiles) |
| Lavanda bolha | `#DCE5FD` | Bolha da usuária, faixa de privacidade |
| Areia | `#EEEADE` | Bolha da assistente |
| Areia clara | `#F0EDE5` | Item de lista, acesso rápido |
| Névoa | `#EDF0ED` | Círculo de ícone, avatar neutro |
| Verde claro | `#D8E9DF` | Fundo de estado disponível |
| Sol claro | `#F7DB8E` | Fundo de ícone de destaque |
| Linha | `#E7E2D8` | Divisor de 1 px em fundos quentes |
| Linha forte | `#D5D6D0` | Borda de cartão e de campo |

### 4.3 Cores de texto e acessibilidade

O manual já fixa a hierarquia de contraste. Medições recalculadas para os fundos usados
na interface (WCAG 2.1, luminância relativa):

| Combinação | Razão | Nível | Uso |
| --- | --- | --- | --- |
| Tinta / Aveia | **12,78:1** | AAA | Texto principal |
| Tinta / Branco quente | **14,27:1** | AAA | Texto principal |
| Tinta / Lavanda bolha | **11,52:1** | AAA | Texto na bolha da usuária |
| Tinta / Areia | **12,06:1** | AAA | Texto na bolha da assistente |
| Branco / Azul pulso | **6,16:1** | AA | Rótulo de botão primário |
| Azul pulso / Aveia | **5,43:1** | AA | Link e rótulo sobre aveia |
| Azul pulso / Lavanda | **4,89:1** | AA | Ícone e link sobre lavanda |
| Branco / Sol | **1,79:1** | ✗ | **Proibido** |
| Tinta / Sol | **8,11:1** | AAA | Texto sobre sol (quando inevitável) |
| Verde folha / Branco quente | 4,09:1 | AA grande | Só ícone ou texto ≥ 24 px |
| Verde texto `#1F6B57` / Branco quente | **6,26:1** | AA | Rótulo "Disponível" |
| Branco / Verde folha `#1F6B57` | **6,26:1** | AA | Botão verde (180) |
| Texto suave `#5C6673` / Branco quente | **5,73:1** | AA | Texto secundário |
| Texto suave `#5C6673` / Areia | 4,85:1 | AA | Texto secundário em cartão |
| Sol texto `#7A4F00` / Sol claro | 5,25:1 | AA | Rótulo de estado "alterado" |
| Névoa `#78828A` / Branco quente | 3,85:1 | AA grande | **Só decoração**, nunca texto pequeno |

**Decisões derivadas** (documentadas porque não estão no manual, mas são necessárias):

1. `--zelia-verde-escuro: #1F6B57` para texto e para o botão "180": o verde de marca com
   branco fica em 4,16:1, abaixo de AA para texto normal.
2. `--zelia-sol-texto: #7A4F00` para rótulos sobre sol claro; o sol puro continua proibido
   como cor de texto.
3. `--texto-suave: #5C6673` (5,73:1) em vez do cinza decorativo `#78828A`.
4. Foco usa azul pulso com anel de 2 px + afastamento de 2 px (contraste ≥ 3:1 contra
   aveia, branco quente e lavanda).

---

## 5. Tipografia

### 5.1 Famílias

| Família | Papel | Por quê |
| --- | --- | --- |
| **Afacad Flux** (variável 100–900) | Voz da interface | Humanista, aberta e compacta. Próxima sem ser infantil; precisa sem parecer institucional. |
| **Newsreader Italic** (variável 200–800) | Gesto editorial | Reservada a frases-conceito e ênfases institucionais. Nunca em corpo de texto corrido. |

Ambas são servidas **localmente** (`web/ui/assets/fonts/`, subconjuntos `latin` e
`latin-ext`, licença SIL OFL 1.1), sem requisição a terceiros — coerente com a promessa
de discrição. Fallback: `system-ui, "Segoe UI", sans-serif` e `Georgia, serif`.

### 5.2 Hierarquia do manual

| Nível | Especificação | Uso |
| --- | --- | --- |
| Display | 64/66 · Semibold | Capa e abertura |
| Título | 32/36 · Medium | Título de tela |
| Corpo | 16/24 · Regular | Leitura |
| Rótulo | 12/16 · Semibold | Categorias, metadados |

Rótulos são caixa alta com **tracking 0,12–0,14 em**. Títulos usam tracking negativo
(≈ -0,03 em) e nunca caixa alta.

### 5.3 Escala web aplicada

| Token | Tamanho / entrelinha | Peso | Onde |
| --- | --- | --- | --- |
| `--texto-display` | `clamp(2.25rem, 1.6rem + 2.4vw, 3.25rem)` / 1.05 | 600 | Título da tela inicial |
| `--texto-titulo` | `2rem` / 1.125 | 500 | Título de seção |
| `--texto-subtitulo` | `1.375rem` / 1.25 | 500 | Cabeçalho de cartão |
| `--texto-corpo-g` | `1.125rem` / 1.5 | 400 | Texto de apoio da abertura |
| `--texto-corpo` | `1rem` / 1.5 | 400 | Corpo padrão, mensagens |
| `--texto-pequeno` | `0.875rem` / 1.45 | 400 | Metadados, legendas |
| `--texto-rotulo` | `0.75rem` / 1.35 | 600 | Rótulos caixa alta, tracking 0,13 em |
| `--texto-micro` | `0.6875rem` / 1.3 | 600 | Contagem, "agora", contadores |

**Mínimos:** corpo nunca abaixo de 16 px em conteúdo de leitura; 14 px só para metadado;
12 px só para rótulo caixa alta com peso 600.

---

## 6. Espaço, grid e forma

### 6.1 Escala de espaço

Base 4 pt: `4, 8, 12, 16, 20, 24, 32, 40, 48, 64, 80, 96`.
Ritmo padrão de bloco: 24 px entre grupos, 16 px entre elementos do mesmo grupo,
8 px entre rótulo e conteúdo.

### 6.2 Layout

| Token | Valor | Uso |
| --- | --- | --- |
| `--largura-max` | 1240 px | Moldura da página |
| `--largura-conversa` | 760 px | Coluna de conversa |
| `--largura-aside` | 320 px | Coluna de contexto |
| `--altura-topo` | 76 px | Cabeçalho |
| Goteira | 24 px (16 px < 640) | Entre colunas |

Breakpoints: **≥ 1200** duas colunas; **960–1199** duas colunas com aside 288 px;
**< 960** uma coluna e o contexto vira painel deslizante; **< 640** margens de 16 px,
bolhas até 88% da largura.

### 6.3 Raios

| Token | Valor | Uso |
| --- | --- | --- |
| `--raio-xs` | 8 px | Selo, tecla |
| `--raio-sm` | 12 px | Tile de ícone |
| `--raio-md` | 16 px | Campo, cartão interno |
| `--raio-lg` | 20 px | Cartão, bolha |
| `--raio-xl` | 24 px | Cartão de contexto |
| `--raio-2xl` | 32 px | Janela principal, abertura |
| `--raio-pill` | 999 px | Chip, botão, composer |

Regra: quanto maior a superfície, maior o raio. O raio nunca compete com o conteúdo —
em cartões muito pequenos, usar `--raio-sm`.

### 6.4 Bordas e elevação

A marca é **plana**. Profundidade vem de superfície e fio de 1 px, não de sombra.

- Borda padrão: `1px solid var(--cor-borda)` (`#E7E2D8`).
- Borda de campo: `1px solid var(--cor-borda-forte)` (`#D5D6D0`).
- Sombra só em sobreposição (painel, menu, diálogo): `--sombra-2`.
- A logo **nunca** recebe sombra.

---

## 7. Sistema visual

Três padrões do manual viram componentes:

| Padrão | Significado | Aplicação |
| --- | --- | --- |
| **Fios de conversa** | Conectam conteúdos e indicam continuidade | Linha curva decorativa na abertura; trilho vertical entre passos numerados |
| **Janelas abertas** | Enquadram sem aprisionar | Cartões com raio grande e fio fino; nunca molduras pesadas |
| **Pontos de presença** | Marcam pessoas, fontes e escolhas | Ponto solar no wordmark; pontos verde/azul/sol em passos e fontes |

### Ícones

Traço de **1,6 px** em grade 24, cantos e terminais arredondados, cor herdada do texto.
Conjunto mínimo usado na interface: cadeado, escudo, telefone, mapa, documento, seta,
chevron, microfone, enviar, check, informação, calendário, link externo, menu, fechar,
olho, ajustes, relógio, sinal indisponível.

Ícone nunca é o único portador de significado: sempre acompanha rótulo ou texto acessível.

---

## 8. Componentes

Especificação dos componentes base. Todos usam os tokens acima; nenhum valor solto.

### 8.1 Botões

| Variante | Fundo | Texto | Borda | Altura |
| --- | --- | --- | --- | --- |
| Primário | Azul pulso | Branco quente | — | 48 px |
| Secundário | Transparente | Tinta | 1 px linha forte | 44 px |
| Fantasma | Transparente | Azul pulso | — | 40 px |
| Ícone | Transparente | Tinta | — | 44 × 44 |
| Destrutivo suave | Transparente | Tinta | 1 px linha forte | 44 px |

Estados: `hover` escurece o fundo em 8% (primário: `#1B46B0`), `active` comprime 0,98,
`focus-visible` anel de 2 px, `disabled` opacidade 0,45 e cursor `not-allowed`.
Nenhum botão usa sombra.

### 8.2 Chips

Pílula de 32 px, borda 1 px `#D5D6D0`, fundo transparente, texto 13 px/500.
Variante selecionada: fundo azul pulso, texto branco. Variante "privacidade": cadeado +
texto, fundo `#E3E9FF`, sem borda.

### 8.3 Campos

Altura 48 px (textarea cresce de 48 a 160 px), raio `--raio-md` (ou `--raio-pill` no
composer), fundo branco quente sobre aveia, borda 1 px `#D5D6D0`, padding 12 × 16.
`focus`: borda azul pulso + anel `0 0 0 4px rgba(36,87,214,.14)`.
Placeholder em `#5C6673` (não em cinza claro).

### 8.4 Cartões

Fundo branco quente, raio 20–24 px, borda 1 px, padding 20–24 px.
Cabeçalho com título 15–17 px/600 e metadado 13 px em texto suave.
Cartão de destaque: fundo lavanda, sem borda. Cartão de ação: fundo azul pulso, texto branco.

### 8.5 Mensagens

| Elemento | Fundo | Raio | Largura |
| --- | --- | --- | --- |
| Bolha da usuária | `#DCE5FD` | 20 px, canto inferior direito 6 px | até 78% |
| Bolha da assistente | `#EEEADE` | 20 px, canto inferior esquerdo 6 px | até 82% |
| Cartão estruturado | Branco quente + fio | 20 px | 100% da coluna de conteúdo |
| Aviso de sistema | `#F0EDE5` | 16 px | 100% |

Avatar da assistente: círculo de 32 px, fundo azul pulso, símbolo branco.
Avatar da usuária: não existe. A usuária não é representada por foto nem por iniciais.

### 8.6 Estados semânticos

| Estado | Fundo | Texto/ícone | Nunca |
| --- | --- | --- | --- |
| Vigente | `#D8E9DF` | `#1F6B57` + check | Verde como único sinal |
| Alterado | `#F7DB8E` | `#7A4F00` + ponto | Texto branco |
| Revogado | `#EDE9E0` | `#5C6673` + traço | Vermelho |
| Indisponível | `#F0EDE5` | `#5C6673` + ícone de sinal | Cinza claro sobre branco |
| Emergência | `#2457D6` | `#FFFDF8` + telefone | Vermelho, ícone de pânico, animação |

---

## 9. Movimento

| Token | Valor | Uso |
| --- | --- | --- |
| `--mov-marca` | 1200 ms | Traço da marca se desenhando |
| `--mov-rapido` | 160 ms | Hover, foco, chip |
| `--mov-padrao` | 240 ms | Entrada de mensagem, acordeão |
| `--mov-lento` | 320 ms | Painel deslizante |
| `--curva-padrao` | `cubic-bezier(.22,.61,.36,1)` | Tudo |
| `--curva-saida` | `cubic-bezier(.4,0,1,1)` | Saída |

Regras: **nada quica** ("o traço percorre o caminho e assenta sem quicar"). Nenhuma
animação acima de 320 ms fora da entrada da marca. Nenhum laço infinito além do indicador
de digitação (pulso de 1,6 s, opacidade 0,35→1). `prefers-reduced-motion: reduce`
desliga o traço, o pulso e as translações; mantém apenas mudanças de opacidade instantâneas.

---

## 10. Voz e tom

**Princípios**

1. Fala com a pessoa, não sobre o caso.
2. Explica o limite antes de prometer.
3. Não julga, não consola demais, não dramatiza.
4. Deixa a decisão com ela ("você decide o ritmo").
5. Usa o nome das coisas (lei, artigo, prazo) e traduz em seguida.

| Faça | Não faça |
| --- | --- |
| "Não encontrei base suficiente para responder com segurança." | "Desculpe, não sei responder isso." |
| "Você pode começar por onde for mais fácil." | "Vamos lá! Você consegue!" |
| "A lei prevê até 48 horas para o juiz decidir." | "A lei garante que você vai conseguir." |
| "Se você está em perigo agora, ligue 190." | "Calma, vai ficar tudo bem." |
| "Orientação informativa. Não substitui atendimento jurídico individual." | "Consulte um advogado." (sem contexto) |

Nunca: diminutivos ("vitimizinha"), imperativo de culpa ("você deveria"), promessa de
resultado, emoji em conteúdo sensível, caixa alta em corpo de texto.

---

## 11. Discreção e privacidade

Decisões de marca que são requisito de produto:

- **Título neutro:** a aba e o título do app são sempre "Zelia · Organização e informação".
  A pergunta da usuária nunca vira título.
- **Notificação sem prévia:** nenhum conteúdo sensível em título, notificação ou histórico
  do navegador.
- **Histórico local:** a conversa só persiste no aparelho, com controle explícito e botão
  de apagar. Padrão **desligado** — o manual ilustra o controle ligado, mas em dispositivo
  compartilhado o padrão seguro é não gravar (decisão registrada em
  [`11-interface-chatbot.md`](11-interface-chatbot.md#12-privacidade-e-discrição)).
- **Sem conta, sem foto, sem nome:** a assistente chama a pessoa de "você".
- **Sem PII no campo:** o composer avisa antes do envio, não depois.
- **Domínio de marca:** o símbolo e o wordmark nunca aparecem sobre conteúdo sensível em
  miniatura de compartilhamento.

---

## 12. Tokens

Fonte de verdade em [`tokens.css`](../web/ui/styles/tokens.css). Nomes:

```
cor        --zelia-*, --cor-fundo, --cor-superficie, --cor-texto, --cor-acao, --cor-borda
tipo       --fonte-texto, --fonte-editorial, --texto-*, --peso-*, --tracking-*
espaço     --esp-1 … --esp-12
forma      --raio-*, --sombra-*, --borda-*
movimento  --mov-*, --curva-*
layout     --largura-*, --altura-topo, --goteira
```

Uso típico:

```css
.card-fonte {
  background: var(--cor-superficie);
  border: var(--borda-fina);
  border-radius: var(--raio-lg);
  padding: var(--esp-5);
  color: var(--cor-texto);
}

.rotulo {
  font: var(--peso-semi) var(--texto-rotulo) / 1.35 var(--fonte-texto);
  letter-spacing: var(--tracking-rotulo);
  text-transform: uppercase;
  color: var(--cor-acao);
}
```

---

## 13. O que a interface acrescenta ao manual

O manual cobre a marca e telas de app móvel. Para a interface web do chatbot, foram
acrescentados — sempre derivados dos mesmos tokens:

1. **Grade de duas colunas** (conversa + contexto) para telas grandes.
2. **Cartões de resposta estruturada** (fontes, próximos passos, encaminhamentos), que o
   manual não detalha.
3. **Bloco de emergência** em azul pulso, com telefones como ações.
4. **Estados de sistema** (carregando, offline, demonstração, abstenção).
5. **Escala tipográfica fluida** para web, preservando as proporções 64/32/16/12.
6. **Tokens de acessibilidade** (foco, texto suave, verde escuro, sol texto).

Tudo o que não está no manual está justificado neste documento ou no plano da interface.
