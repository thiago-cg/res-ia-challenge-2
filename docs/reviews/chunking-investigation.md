# Semantic chunking: o que o corpus permite ganhar

Investigação medida em 2026-11-07 contra o corpus carregado (4.959 versões de
dispositivo, 1.312 artigos, 5 normas) e o índice Qdrant `qwen/qwen3-embedding-8b`
4096d. Todos os números vêm de consultas reais; nenhuma estimativa não marcada.

## Resumo

O corpus **já é chunkado na unidade semântica da lei** (artigo, caput, parágrafo,
inciso, alínea), com contexto determinístico. Não sobra documento longo para
quebrar: 64,8% dos dispositivos têm **uma única frase** e o maior dispositivo tem
117 palavras. Por isso o ganho esperado de *chunking semântico* (determinístico
ou por LLM) é próximo de zero e o efeito colateral é negativo.

O ganho existe na direção oposta: **contexto preciso**, não mais texto. Retirar o
contexto do chunk custa 25 a 31 pontos de recall@10; acrescentar contexto de forma
ingênua custa 10 pontos. O gargalo restante não está no chunking, e sim na
granularidade da deduplicação (recall@10 por artigo é 1,000 e por dispositivo é
0,850).

## Como o corpus é chunkado hoje

Um chunk por `(device_id, norm_version_id)`. O texto indexado é
`contexto` (cabeçalho determinístico: norma, título, capítulo, artigo, caminho)
mais `texto_literal`. Ver `src/index/chunk.py` e `docs/04`.

| Medida | Valor |
| --- | ---: |
| Dispositivos | 4.959 |
| Palavras do `texto_literal` | mediana 23, p99 76, máx 117 |
| Palavras do texto indexado (contexto + literal) | mediana 34, p99 85, máx 128 |
| Frases por dispositivo | média 1,48; 64,8% com uma frase; 501 com 3+ |
| Contexto como fração do texto indexado | 29,8% |
| Strings de contexto distintas | 68 (para 4.959 linhas) |
| Dispositivos que começam com minúscula (fragmento dependente) | 1.153 (23,2%) |
| Dispositivos com anáfora jurídica ("esta lei", "o agressor", ...) | 445 (9,0%) |

O "documento" natural é o artigo: média de 96 palavras, p50 76, p90 178, máximo
771. Apenas 32 artigos passam de 300 palavras e 10 passam de 512.

## Experimento A/B

Duas variantes foram reindexadas em paralelo (mesmo encoder, mesma instrução de
consulta, filtro de vigência idêntico), com 4.959 pontos cada:

- **só literal** — apenas `texto_literal`;
- **enriquecido** — título da norma + cabeçalho + `texto_literal` do artigo +
  rótulo do tipo + literal do dispositivo.

Avaliação sobre as 10 perguntas respondíveis de `data/eval/questions.jsonl`,
top-10 bruto (sem dedupe), para isolar o efeito do chunk:

| Configuração | Recall@10 dispositivo | Recall@10 artigo | MRR@10 | nDCG@10 |
| --- | ---: | ---: | ---: | ---: |
| Índice atual + consulta expandida | **1,000** | **1,000** | 0,548 | **0,631** |
| Enriquecido + consulta expandida | 0,900 | 1,000 | 0,547 | 0,592 |
| Só literal + consulta expandida | 0,750 | 0,950 | **0,550** | 0,544 |
| Índice atual + consulta crua | 0,633 | 0,733 | 0,361 | 0,402 |
| Enriquecido + consulta crua | 0,633 | 0,733 | **0,410** | **0,432** |
| Só literal + consulta crua | 0,483 | 0,733 | 0,500 | 0,397 |

Leituras:

1. **O contexto no chunk vale 25–31 pontos** de recall@10 (0,750 → 1,000 com
   consulta expandida; 0,483 → 0,633 com consulta crua). O desenho do `docs/04`
   está certo.
2. **Contexto ingênuo piora**: somar título da norma e o literal inteiro do
   artigo derrubou o recall de 1,000 para 0,900. Mais texto não é mais sinal: os
   dispositivos-irmãos passam a colidir entre si.
3. **A reescrita de consulta continua sendo o maior fator isolado** (0,633 →
   1,000 no índice atual). É exatamente o ponto frágil já documentado: as regras
   foram escritas olhando este conjunto.

## Por técnica

### Chunking semântico determinístico

Quebrar por frase/fronteira semântica não tem o que quebrar: 64,8% dos
dispositivos são uma frase só. Os 19 dispositivos-ouro do conjunto de avaliação
virariam 29 fragmentos (média 1,53), e cada fragmento perde a identidade do
dispositivo que o gold exige. O top-10 já gasta 4,5 das 10 vagas em dispositivos
do mesmo artigo (média de 5,5 artigos distintos por consulta); fragmentar
aumentaria essa concentração.

### Chunking dinâmico por LLM

Mesmo teto de headroom. O custo seria de 1.744 dispositivos com duas ou mais
frases, cada um exigindo uma chamada de LLM para decidir cortes — cerca de 2.245
chamadas por reindexação completa, com latência e custo recorrentes, e perda de
determinismo (o `embedding_text_hash` deixa de ser reprodutível). Onde o LLM
teria algo a decidir seria no **agrupamento** (fundir §§ de um mesmo artigo),
não no corte.

### Late chunking

Técnica que embeda o documento inteiro e faz pooling dos embeddings de token por
trecho, de modo que cada chunk carregue o contexto do documento. Requer modelo de
contexto longo que exponha estados por token, **o mesmo** para documento e
consulta.

No stack atual é inviável, e a evidência é direta:

- o provedor é o OpenRouter, cuja API de embeddings devolve um vetor já agregado
  por entrada, sem opção de saída por token;
- não há `torch`, `transformers` nem `sentence-transformers` instalados, e não
  há GPU; os artefatos locais do repositório são GGUF, que o projeto rejeita com
  `ModelFormatError`.

Mesmo se implementado, o teto é o mesmo do experimento acima: o documento
natural (artigo) tem p50 de 76 palavras e só 10 artigos passam de 512 palavras.
Como o enriquecimento textual — que injeta a mesma informação — não superou o
índice atual, o ganho esperado de late chunking neste corpus é pequeno; o teste
definitivo exigiria inferência local com um modelo que exponha hidden states.

### Enriquecimento com estrutura jurídica

É a direção com fundamento empírico (o contexto já vale 25–31 pontos), mas o
resultado mostra que o ganho depende de **precisão**, não de volume. A variante
testada somou três coisas de uma vez e perdeu 10 pontos; não foi possível
atribuir a perda a um componente isolado. O próximo passo correto é isolar:

- caput apenas para os 23,2% de fragmentos que começam com minúscula;
- sinônimos jurídicos determinísticos no índice (o que substituiria parte das
  regras de consulta, hoje escritas sobre o conjunto de avaliação);
- rubrica do artigo, quando existir no corpus.

## Onde está o ganho que sobra

O recall@10 por artigo é 1,000 e por dispositivo é 0,850 no benchmark de
produção: a recuperação acha o artigo certo e perde o dispositivo por causa da
deduplicação por artigo e da expansão de contexto. Os itens já registrados no
README (dedupe preferindo especificidade a score; `expand_to_article` sem a
linha do artigo em 13% das folhas) valem mais que qualquer reindexação.

## Reprodução

A coleção de teste `devices_chunk_experiment` foi removida após a medição.
Para repetir: crie uma coleção com dois vetores nomeados (`lit`, `enriched`),
codifique as duas variantes de texto com `encode_documents` do encoder de
produção, consulte com `encode_query` e o mesmo filtro de vigência de
`src.index.qdrant`, e compare top-10 bruto contra `devices_qdrant_dense_v1`
nas 10 perguntas respondíveis. A indexação das duas variantes custou cerca de
15 minutos e ~10 mil embeddings.