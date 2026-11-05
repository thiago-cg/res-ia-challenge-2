# 05 — Embeddings e recuperação

## 0. Escopo desta versão

| Item                               | Decisão                                                     |
| ---------------------------------- | ----------------------------------------------------------- |
| Alvo (9B/0.6B + Qdrant)            | Obrigatório quando houver GPU; é o caminho de qualidade.    |
| Fallback (Harrier + pgvector/FTS)  | Contingência para rodar sem GPU; não é o desenho combinado. |
| Loop agêntico e grafo de remissões | Pós-MVP; não bloqueiam a primeira entrega.                  |
| Doc2query                          | Pós-MVP; o schema já reserva espaço.                        |

## 1. Requisitos

| Requisito                                              | Por que                                                                |
| ------------------------------------------------------ | ---------------------------------------------------------------------- |
| Português jurídico                                     | O corpus é lei brasileira; o vocabulário é institucional               |
| Instrução separada para consulta e documento           | A pergunta da vítima e o dispositivo não têm a mesma forma             |
| Dimensão ajustável (Matryoshka) ou pooling             | Espaço e latência                                                      |
| Privacidade                                            | Perguntas de vítimas são dados sensíveis (LGPD)                        |
| Late interaction (desejável)                           | Casamento token a token ajuda em "art. 24-A", "inciso III", "alínea b" |
| Licença permissiva                                     | Protótipo e possível produto                                           |
| Mesmo espaço vetorial/família para indexar e consultar | Evitar espaço vetorial incompatível                                    |

## 2. Modelos candidatos

### Open weights

| Modelo                                           | Licença                     | Dimensão       | Contexto | Pontos fortes                                                                 | Ressalvas                                                                          |
| ------------------------------------------------ | --------------------------- | -------------- | -------- | ----------------------------------------------------------------------------- | ---------------------------------------------------------------------------------- |
| `microsoft/harrier-oss-v1-0.6b`                  | MIT                         | 1024           | 32k      | 69,0 no MMTEB v2; leve; instrução na consulta                                 | Denso; português jurídico não é recorte público                                    |
| `microsoft/harrier-oss-v1-27b`                   | MIT                         | 5376           | 131k     | 74,3 no MMTEB v2; topo open-weight                                            | Muito pesado para protótipo local                                                  |
| `perplexity-ai/pplx-embed-v2-late-0.6b`          | MIT                         | 128/token      | —        | Late interaction; 340M ativos; consulta barata; espaço compartilhado com o 9B | Requer `sentence-transformers>=6.0` e `transformers>=5.4`; armazenamento por token |
| `perplexity-ai/pplx-embed-v2-late-9b`            | MIT                         | 128/token      | —        | 7,4B ativos; indexa com 9B e consulta com 0,6B                                | 33,6 GB de pesos em F32; GPU grande                                                |
| `perplexity-ai/pplx-embed-v2-context-9b-preview` | Verificar no card (preview) | consultar card | —        | Contextual; bom para doutrina/acórdãos                                        | Preview; código customizado; consulta e documento no mesmo modelo; GPU             |
| `Qwen/Qwen3-Embedding-0.6B`                      | Apache 2.0                  | 1024           | 32k      | Forte baseline; leve; instruções                                              | Denso; validar português jurídico                                                  |
| `Qwen/Qwen3-Embedding-8B`                        | Apache 2.0                  | 4096           | 32k      | Qualidade alta; adaptações jurídicas brasileiras no JUÁ                       | Pesado; dimensão grande                                                            |

Links:

- https://huggingface.co/perplexity-ai/pplx-embed-v2-late-0.6b
- https://huggingface.co/perplexity-ai/pplx-embed-v2-late-9b
- https://huggingface.co/perplexity-ai/pplx-embed-v2-context-9b-preview
- https://huggingface.co/microsoft/harrier-oss-v1-0.6b
- https://huggingface.co/microsoft/harrier-oss-v1-27b
- https://huggingface.co/Qwen/Qwen3-Embedding-0.6B
- https://huggingface.co/Qwen/Qwen3-Embedding-8B
- Relatório técnico do pplx v2 late: https://arxiv.org/abs/2610.29523

Os IDs canônicos são os da coluna **Modelo**; `0.6B` e `9B` são apenas abreviações. Em código e configuração, use o nome completo com `org/model`.

### API

| Modelo               | Pontos fortes                                                                   | Ressalvas                                                                |
| -------------------- | ------------------------------------------------------------------------------- | ------------------------------------------------------------------------ |
| Voyage-4 (família)   | Espaço compartilhado entre tamanhos; `voyage-context-4` para chunks contextuais | Consulta sai da infraestrutura; exigir retenção zero e contrato          |
| Gemini Embedding 2   | Boa qualidade multilíngue                                                       | Limite de tokens por entrada (o 001 tinha 2.048); verificar versão atual |
| Cohere/Voyage rerank | Rerank forte com instrução                                                      | API; custo e privacidade                                                 |

### Rerankers

| Modelo                    | Licença              | Uso                                          |
| ------------------------- | -------------------- | -------------------------------------------- |
| `pplx-embed-v2-late-0.6b` | MIT                  | Rerank local por MaxSim (recomendado no MVP) |
| `Qwen3-Reranker-0.6B`     | Apache 2.0           | Fallback local cross-encoder                 |
| Voyage rerank-2.5         | Comercial            | Instrução de direcionamento; API             |
| Cohere Rerank 4 Pro       | Comercial            | API                                          |
| Zerank 2                  | Pesos não comerciais | Evitar no produto                            |

## 3. Decisão de arquitetura

### Caminho-alvo (com GPU) — o desenho combinado

```text
Indexação:  pplx-embed-v2-late-9b -> multivector no Qdrant (MaxSim)
Consulta:   pplx-embed-v2-late-0.6b -> mesmo espaço vetorial
Lexical:    BM25/Qdrant sparse (ou FTS no Postgres)
```

Por quê:

- O 9B indexa com mais qualidade; o 0.6B consulta com latência baixa.
- Os dois compartilham o mesmo espaço vetorial, então o índice do 9B pode ser consultado pelo 0.6B.
- O Qdrant faz MaxSim nativo, sem trazer todos os vetores para o Python.
- O Postgres continua como fonte da verdade de normas, versões, citações e auditoria.
- O corpus inicial é pequeno; o custo de indexar com 9B é aceitável.

Requisitos:

- GPU com memória suficiente: 33,6 GB em F32; ~17 GB em FP16 + overhead. 24 GB é borderline; 48 GB é confortável.
- Qdrant no stack, com vetores `late` (max_sim) e `bm25` (idf).
- O limite do Qdrant é `nº de subvetores × dimensão < 1.048.576`; com 128 dimensões, cabem ~8.192 tokens por ponto. Os dispositivos legais ficam muito abaixo disso.

### Contrato Qdrant

Fixar a versão do servidor e do client. O baseline do protótipo é `qdrant/qdrant:v1.15.3` (mínimo para BM25 server-side) e `qdrant-client` fixado no `pyproject.toml`. Subir a versão só depois que o teste de integração passar.

Coleção `devices_qdrant_current` (alias para a coleção ativa):

| Elemento         | Configuração                                                                                                        |
| ---------------- | ------------------------------------------------------------------------------------------------------------------- |
| Vetor `late`     | `size=128`, `distance=Cosine`, `multivector_config.comparator=max_sim`, `datatype=float16`                          |
| Vetor `bm25`     | esparso, `modifier=idf`, nome `bm25`                                                                                |
| Payload indexado | `norm_id`, `norm_version_id`, `artigo_id`, `tipo`, `vigencia_status`, `vigencia_inicio`, `vigencia_fim`             |
| ID do ponto      | `UUIDv5(namespace, f"{device_id}@{norm_version_id}")`                                                               |
| Upsert           | um ponto por `(device_id, norm_version_id)`; versões antigas permanecem indexadas                                   |
| Query            | prefetch `bm25` top 100; rescore `late` (MaxSim) sobre até 150; filtro de vigência; `limit=10`; `with_payload=true` |

O payload não carrega o texto completo: a hidratação vem do Postgres por `(device_id, norm_version_id)`, conforme o schema do documento 04. A API exata do client é coberta pelo teste de integração; o contrato acima é o que não pode variar.

### Fallback sem GPU — contingência

```text
Indexação:  harrier-oss-v1-0.6b -> pgvector (denso)
Consulta:   harrier-oss-v1-0.6b -> pgvector + FTS
Rerank:     pplx-embed-v2-late-0.6b sobre o top 50 (opcional)
```

Esse caminho existe para o protótipo rodar em qualquer máquina. Ele **não** é o desenho combinado: perde o índice multivector do 9B e usa outro espaço vetorial na primeira etapa. O Harrier é fallback, não a escolha principal.

| Critério        | Alvo (9B/0.6B)        | Fallback (Harrier + 0.6B)    |
| --------------- | --------------------- | ---------------------------- |
| Qualidade       | Maior                 | Boa, mas abaixo do 9B        |
| GPU             | Necessária            | Opcional                     |
| Armazenamento   | Multivector por token | Vetor denso por chunk        |
| Complexidade    | Qdrant + MaxSim       | Postgres + pgvector + rerank |
| Uso recomendado | Núcleo e produção     | Demo local e contingência    |

> Correção em relação à primeira versão desta doc: o Harrier havia sido colocado como recomendação principal por não haver confirmação de GPU. O alvo é o pplx 9B/0.6B; o Harrier fica explicitamente como fallback.

### Alternativa API

Se a privacidade for resolvida por contrato:

- Voyage-4 para indexar/consultar;
- `voyage-context-4` para doutrina/acórdãos;
- rerank Voyage/Cohere com instrução.

Sem contrato de retenção zero, **não** envie perguntas de vítimas.

## 4. Hardware e armazenamento

| Item                                          | Estimativa                        |
| --------------------------------------------- | --------------------------------- |
| Harrier 0.6B                                  | ~1,2 GB em FP16                   |
| pplx late 0.6B                                | ~1,2 GB em FP16                   |
| pplx late 9B                                  | 33,6 GB em F32; ~17 GB em FP16    |
| 100 mil chunks densos (1024 dims, FP32)       | ~410 MB + índice HNSW             |
| 10 milhões de tokens em late (128 dims, FP16) | ~2,56 GB + overhead               |
| Qdrant local                                  | Disco proporcional ao multivector |

O corpus inicial (LMP + trechos do CP/CPP + súmulas + atos) é pequeno: dezenas de milhares de dispositivos no máximo. O gargalo será qualidade, não volume.

### Configuração de execução

| Parâmetro           | Alvo                                                     | Fallback                                           |
| ------------------- | -------------------------------------------------------- | -------------------------------------------------- |
| Modelo de indexação | `perplexity-ai/pplx-embed-v2-late-9b`, `revision` fixada | `microsoft/harrier-oss-v1-0.6b`, `revision` fixada |
| Modelo de consulta  | `perplexity-ai/pplx-embed-v2-late-0.6b`                  | `microsoft/harrier-oss-v1-0.6b`                    |
| `dtype`             | `bfloat16` no 9B; `float16` no 0.6B                      | `float16`                                          |
| `device`            | `cuda`                                                   | `cuda` ou `cpu`                                    |
| Batch de indexação  | 1 (9B)                                                   | 32                                                 |
| Batch de consulta   | 8                                                        | 1–8                                                |
| `max_length`        | 8.192 tokens no documento; 512 na consulta               | 8.192 tokens no documento; 512 na consulta         |
| `truncation`        | `true`, cortando contexto antes do texto literal         | `true`, mesma regra                                |
| Normalização        | L2 no vetor final                                        | L2 no vetor final                                  |
| OOM                 | reduzir batch para 1; depois quantizar; depois fallback  | reduzir batch; depois CPU                          |

Regras:

- O texto literal nunca é truncado antes da pena/inciso final; corte primeiro o contexto e a explicação.
- Se `contexto + texto_literal` exceder `max_length`, dividir o dispositivo por subnós estruturais (incisos/alíneas) ou falhar a ingestão com alerta; nunca truncar o literal. O contexto pode ser reduzido ao caput + caminho mínimo.
- O 9B e o 0.6B usam o mesmo espaço vetorial; não carregue o Harrier no mesmo índice.
- Registre `embedding_model_revision` e `embedding_text_hash` por versão de dispositivo.
- O `max_length` do modelo pplx deve ser confirmado no card da revisão usada; o limite de 8.192 tokens é o do Qdrant para 128 dimensões.

## 5. Pipeline de indexação

### Caminho-alvo

```text
1. Ler dispositivos e versões do Postgres (device_versions).
2. Montar o texto de indexação:
   contexto determinístico + texto_literal
2b. Se `contexto + literal` > `max_length`, dividir por subnós
    estruturais ou falhar com alerta; não truncar o literal.
3. Codificar com pplx-embed-v2-late-9b:
   encode_document([texto_de_indexacao]) -> matriz (tokens x 128)
4. Calcular o ID do ponto:
   UUIDv5(namespace, f"{device_id}@{norm_version_id}")
5. Upsert no Qdrant:
   - vetor multivector `late` (max_sim, float16);
   - vetor esparso `bm25` (modifier=idf);
   - payload com device_id, norm_version_id, norm_id, artigo_id,
     tipo, vigencia_status, vigencia_inicio, vigencia_fim.
6. Popular `search_text` normalizado; o BM25 usa
   contexto + texto_literal + citação.
7. Opcional (pós-MVP): explicação e perguntas (doc2query).
8. Registrar embedding_model, revisão, hash do texto e data do índice.
```

### Fallback sem GPU

```text
1. Ler dispositivos e versões do Postgres (device_versions).
2. Montar o texto de indexação.
3. Codificar com harrier-oss-v1-0.6b:
   model.encode([texto_de_indexacao])
4. Gravar em device_versions.embedding e embedding_model.
5. Popular search_text normalizado para FTS.
6. Opcional (pós-MVP): doc2query.
7. Registrar revisão do modelo e hash do texto.
```

Regras:

- No caminho-alvo, o índice é feito com o 9B e a consulta com o 0.6B; os dois compartilham o espaço vetorial.
- No fallback, o Harrier indexa e consulta; o pplx 0.6B só reordena.
- Não misture Harrier no índice com pplx na consulta: são espaços diferentes.
- O documento **não** recebe a instrução de tarefa do Harrier; só a consulta.
- O texto literal nunca é alterado pelo enriquecimento.
- Se o modelo mudar, reindexar e atualizar `embedding_model`/`embedding_model_revision`; não misturar espaços.

## 6. Pipeline de consulta

### Caminho-alvo

```text
0. Citação explícita ("art. 22", "art. 24-A", "inciso III"):
   resolver direto para device_id + versão.
   - inequívoca e encontrada: usar o ID;
   - inequívoca e inexistente/fora do corpus: abster com
     "dispositivo não encontrado"; não cair para híbrida;
   - ambígua: usar o contexto da conversa; se ainda ambígua,
     perguntar; só então busca híbrida.
1. Normalizar a pergunta (sem acento, minúsculas).
2. Extrair fatos (contrato de entendimento da consulta):
   relação com o agressor, tipo de violência, urgência, data do fato.
3. Reescrever em linguagem jurídica.
4. Dividir em até 3 subperguntas.
5. Para cada subpergunta, em paralelo:
   a. prefetch `bm25` top 100 no Qdrant, com filtro de vigência;
   b. unir as subperguntas (máx. 150 candidatos).
6. MaxSim com pplx 0.6B sobre os 150.
7. Deduplicar globalmente por artigo_id, mantendo a folha de maior MaxSim.
8. Selecionar 10 dispositivos; expandir para o artigo completo.
9. Hidratar texto, citação e explicação no Postgres por
   (device_id, norm_version_id).
10. Montar o contexto com IDs, citação, texto e explicação.
```

### Fallback sem GPU

```text
0. Citação explícita: resolver direto por ID (mesma regra do alvo).
1. Normalizar a pergunta.
2. Extrair fatos (contrato de entendimento da consulta).
3. Reescrever e dividir em subperguntas (máx. 3, em paralelo).
4. Para cada subpergunta:
   a. busca densa no pgvector (top 50, operador `<=>`);
   b. busca lexical no FTS (top 50, `websearch_to_tsquery`);
   c. fundir por RRF (k=60);
   d. unir as subperguntas (máx. 150).
5. Rerank opcional com pplx 0.6B sobre o top 50.
6. Deduplicar por artigo, mantendo a folha de maior score.
7. Selecionar 10 dispositivos; expandir para o artigo completo.
8. Hidratar texto, citação e explicação no Postgres.
9. Montar o contexto.
```

### Citação explícita

- Detectar `art.`, `artigo`, `§`, `parágrafo`, `inciso`, `alínea` e `item` com uma gramática única.
- Resolver para `norm_id` + `artigo_id` e, quando houver versão, `device_id` + `norm_version_id`.
- Precedência: citação explícita > busca híbrida.
- Citação inequívoca e inexistente: abster; não usar a busca híbrida como fallback.
- Se ambíguo (ex.: “art. 22” sem lei), usar a lei do contexto da conversa ou perguntar; só depois buscar.
- Testes obrigatórios: `art. 7º`, `art. 24-A`, `inciso III`, `alínea b` e artigo inexistente (este último deve abster, não trazer artigo vizinho).

### Contrato de entendimento da consulta

```json
{
  "fatos": {
    "relacao": "companheiro|ex-companheiro|familiar|outro|desconhecido",
    "tipo_violencia": [
      "fisica",
      "psicologica",
      "sexual",
      "patrimonial",
      "moral",
      "vicaria"
    ],
    "urgencia": "imediata|recente|passada|desconhecida",
    "data_fato": "YYYY-MM-DD|null",
    "uf": "SP|null"
  },
  "consulta_juridica": "string",
  "subperguntas": ["string"]
}
```

- Parse falhou ou JSON inválido: usar a pergunta original como única subpergunta e `fatos` vazio.
- Prompt versionado: `query_understanding_v1`.
- `data_fato` é opcional, mas vira obrigatória quando a pergunta depende de prazo ou de mudança de redação.

| Situação                                | Ação                                                   |
| --------------------------------------- | ------------------------------------------------------ |
| Prazo/versão e `data_fato` ausente      | Perguntar uma vez                                      |
| Usuária não informa a data              | Responder com a lei vigente hoje e declarar a premissa |
| Fato antigo com mudança legal relevante | Exigir a data ou abster                                |
| Data ambígua                            | Perguntar ou declarar a premissa; nunca inventar       |

Alinhamento com o documento 06: data indispensável e ausente leva a perguntar; sem resposta, declarar a premissa ou abster.

### SQL do fallback

```sql
-- denso (Harrier + instrução)
SELECT dv.device_id, dv.norm_version_id,
       1 - (dv.embedding <=> :q) AS score
FROM device_versions dv
WHERE dv.vigencia_status IN ('vigente', 'alterado')
  AND dv.embedding IS NOT NULL
ORDER BY dv.embedding <=> :q
LIMIT 50;

-- lexical (search_text normalizado)
SELECT dv.device_id, dv.norm_version_id,
       ts_rank_cd(dv.search_vector,
                  websearch_to_tsquery('portuguese', :q)) AS score
FROM device_versions dv
WHERE dv.search_vector @@ websearch_to_tsquery('portuguese', :q)
  AND dv.vigencia_status IN ('vigente', 'alterado')
ORDER BY score DESC
LIMIT 50;
```

- `:q` denso = subpergunta reescrita + instrução do Harrier.
- `:q` lexical = subpergunta normalizada.
- Com data do fato, trocar o filtro por `vigencia_inicio <= :data_fato AND (vigencia_fim IS NULL OR vigencia_fim >= :data_fato)`.

### Normalização para BM25

Expandir e padronizar as formas de citação no índice e na consulta:

| Entrada                           | Normalizado                                         |
| --------------------------------- | --------------------------------------------------- |
| `art. 7º` / `artigo 7` / `art 7°` | `artigo 7`                                          |
| `§ 1º` / `parágrafo primeiro`     | `paragrafo 1`                                       |
| `inc. II` / `inciso II`           | `inciso 2`                                          |
| `al. b` / `alínea b`              | `alinea b`                                          |
| `24-A`                            | `24-a` (preservar hífen)                            |
| `BO`                              | `boletim de ocorrencia`                             |
| `medida protetiva`                | `medida protetiva` (sinônimo: `medida de protecao`) |

Gramática de citações (aplicar na mesma função no índice e na consulta):

| Entrada              | Normalizado                           |
| -------------------- | ------------------------------------- |
| `arts. 5º e 6º`      | `artigo 5 artigo 6`                   |
| `§§ 1º a 3º`         | `paragrafo 1 paragrafo 2 paragrafo 3` |
| `incisos I e II`     | `inciso 1 inciso 2`                   |
| `alíneas a e b`      | `alinea a alinea b`                   |
| `art. 7º, inciso II` | `artigo 7 inciso 2`                   |
| `art. 24-A`          | `artigo 24-a`                         |
| `art. 5º, § 1º`      | `artigo 5 paragrafo 1`                |

- Expandir intervalos (`a`, `até`, `-`) para cada valor.
- Preservar o hífen em `24-A`; não confundir com intervalo.
- Usar `unaccent` + configuração `portuguese`; a mesma função gera `search_text` no índice e na consulta.
- Fixtures de teste obrigatórias para cada linha da tabela.

Não normalizar demais: "representação", "queixa" e "denúncia" têm sentidos técnicos diferentes. Use sinônimos com cuidado e mantenha o texto original para o embedding.

### Codificação da consulta com Harrier

O Harrier é instruction-aware: a instrução vai na consulta, não no documento.

```python
INSTRUCTION = (
    "Instruct: Dada uma pergunta de uma vítima de violência doméstica, "
    "recupere o dispositivo legal que a responde.\nQuery: "
)

query_embedding = model.encode([INSTRUCTION + pergunta])
document_embedding = model.encode([contexto + texto_literal])
```

### Filtro de vigência

Padrão:

```sql
WHERE vigencia_status IN ('vigente', 'alterado')
```

Com data do fato:

```sql
WHERE vigencia_inicio <= :data_fato
  AND (vigencia_fim IS NULL OR vigencia_fim >= :data_fato)
```

Sem data do fato, usar a versão vigente hoje. Se a pergunta envolve prazo ou mudança recente, perguntar a data ou sinalizar a premissa.

### RRF

```python
def rrf(rank_lists, k=60):
    scores = {}
    for ranks in rank_lists:
        for position, device_id in enumerate(ranks, start=1):
            scores[device_id] = scores.get(device_id, 0.0) + 1.0 / (k + position)
    return sorted(scores.items(), key=lambda item: item[1], reverse=True)
```

### Deduplicação e expansão

- Primeiro MaxSim nas folhas; depois agrupar por `artigo_id` e manter a folha de maior MaxSim.
- No fallback sem MaxSim, usar o maior RRF.
- Subir para o artigo inteiro para o contexto.
- Seguir remissões só se o grafo existir; no MVP, expansão estrutural (pai/artigo).
- Nunca deixar 10 chunks do mesmo artigo ocuparem o contexto.

## 7. MaxSim e rerank

### Caminho-alvo (Qdrant)

No alvo, o MaxSim roda dentro do Qdrant. A coleção tem um vetor multivector `late` (128 dims, comparador `max_sim`); a consulta é codificada com o 0.6B.

Fluxo recomendado:

```text
1. Prefetch `bm25` top 100 com filtro de vigência.
2. Unir as subperguntas (máx. 150 candidatos).
3. Rescore dos até 150 candidatos com o multivector do 0.6B (MaxSim).
4. Top 10 com payload (device_id, norm_version_id, vigência, tipo).
5. Hidratar texto, citação e explicação no Postgres.
```

A API exata do client é coberta pelo teste de integração; o contrato da seção 3 é o que não pode variar. O ponto arquitetural é: **o MaxSim acontece no índice**, não trazendo todos os vetores para o Python.

### Fallback sem GPU

Rerank em memória sobre o top 50:

```python
import os
from sentence_transformers import MultiVectorEncoder

MODEL_ID = "perplexity-ai/pplx-embed-v2-late-0.6b"
DEVICE = os.getenv("PPX_DEVICE", "cuda")
BATCH = int(os.getenv("PPX_QUERY_BATCH", "8"))

model = MultiVectorEncoder(MODEL_ID, device=DEVICE)


def rerank(pergunta: str, textos: list[str]) -> list[float]:
    query_vectors = model.encode_query([pergunta])
    doc_vectors = model.encode_document(textos, batch_size=BATCH)
    return model.similarity(query_vectors, doc_vectors).tolist()
```

Cuidados:

- Use `MultiVectorEncoder` nativo.
- Não use PyLate para este modelo: o PyLate insere os marcadores de pergunta/documento na segunda posição; este modelo espera na primeira.
- Não misture texto e imagem no mesmo batch.
- Requer `sentence-transformers>=6.0.0` e `transformers>=5.4.0`.
- Se não houver GPU, o `Qwen3-Reranker-0.6B` (Apache 2.0) é uma alternativa mais leve; ou pule o rerank e use RRF + regras de prioridade.
- Nunca usar um reranker cujo peso não permita uso comercial no produto.

### Ordem final no contexto

1. Constituição e lei.
2. Súmula, tese e precedente vinculante.
3. Ato do CNJ/CNMP.
4. Doutrina.

Dentro de cada categoria, ordenar por score do rerank. O LLM deve saber o peso da fonte para escolher o verbo: "a lei garante", "o STJ entende", "segundo artigo de...".

### Hidratação e orçamento de contexto

- O payload do Qdrant não contém texto; hidratar por `(device_id, norm_version_id)` com a query do documento 04.
- Orçamento total do contexto: 6.000 tokens.
- O texto literal nunca é truncado; a explicação tem limite de 200 tokens; doutrina é cortada primeiro.
- Se a hidratação falhar, descartar o dispositivo e registrar `incomplete_context`.
- A resposta só pode usar IDs hidratados com sucesso.

## 8. Loop agêntico curto

O agente não é um chat livre. É um orquestrador com ferramentas fixas:

| Ferramenta              | Entrada                   | Saída                         |
| ----------------------- | ------------------------- | ----------------------------- |
| `buscar`                | subpergunta + filtros     | lista de `device_id` + versão |
| `obter_dispositivo`     | `device_id` + versão/data | texto + metadados             |
| `expandir_remissoes`    | `device_id`               | IDs relacionados              |
| `versao_em`             | `norm_id` + data          | `norm_version_id` (evento)    |
| `buscar_jurisprudencia` | tema + filtros            | súmulas/teses                 |

Regras:

- Máximo de 3 voltas.
- Cada subpergunta precisa de evidência; se não houver, reformular uma vez.
- Se ainda faltar base, abster e encaminhar.
- O agente nunca escreve citação nem inventa ID.
- O texto recuperado é dado, não instrução.

## 9. Orçamento de latência

| Etapa                                  | Meta              |
| -------------------------------------- | ----------------- |
| Roteador de risco                      | < 50 ms           |
| Entendimento da consulta               | 300–800 ms        |
| Citação explícita (busca direta)       | < 100 ms          |
| Busca das 3 subperguntas (em paralelo) | 300–600 ms        |
| União e dedupe                         | < 50 ms           |
| MaxSim (até 150 candidatos)            | 300–600 ms em GPU |
| Hidratação no Postgres                 | < 100 ms          |
| Geração                                | 1–3 s             |
| Verificação                            | 300–800 ms        |
| **Total p95 (alvo)**                   | **≤ 8 s**         |
| **Total p95 (fallback CPU)**           | **≤ 10 s**        |

As 3 subperguntas rodam em paralelo. Se a latência estourar, corte o MaxSim para top 100, reduza para 2 subperguntas ou use um LLM menor no entendimento. Meça p50/p95 no conjunto de avaliação com o hardware registrado.

## 10. Como escolher o modelo

Não decida só pelo MTEB. O JUÁ é o benchmark de recuperação jurídica brasileira e ajuda a montar a lista curta. A decisão final sai do seu conjunto de testes.

**A aposta combinada é a opção 1.** As demais são fallback ou baseline:

1. **pplx late 9B index / 0.6B query** (alvo; exige GPU e Qdrant).
2. pplx late 0.6B para indexar e consultar (se o 9B não couber).
3. Harrier + BM25 + pplx late 0.6B rerank (fallback sem GPU).
4. harrier-oss-v1-0.6b denso (baseline).
5. Harrier + BM25 (baseline).

Medir:

- recall@10 por dispositivo;
- nDCG@10;
- precisão da citação;
- latência p95;
- custo por 1.000 perguntas.

## 11. Armadilhas

| Armadilha                                 | Efeito                            | Correção                                         |
| ----------------------------------------- | --------------------------------- | ------------------------------------------------ |
| Usar PyLate com pplx                      | Qualidade cai sem erro            | `MultiVectorEncoder` nativo                      |
| Misturar modelos de indexação e consulta  | Espaços incompatíveis             | Mesmo modelo ou família com espaço compartilhado |
| Indexar texto riscado                     | Duas penas, duas regras           | Remover `<s>`/`<strike>`                         |
| Chunk por tamanho                         | Perde caput/inciso                | Chunk estrutural                                 |
| Ignorar data do fato                      | Aplica lei nova a fato antigo     | Filtro de vigência                               |
| Confiar só no vetor                       | Perde "art. 24-A"                 | BM25 esparso obrigatório                         |
| Não normalizar citação                    | "art. 7º" não casa com "artigo 7" | Normalização no índice e na consulta             |
| Enviar pergunta para API                  | Vazamento de PII                  | Embedder local ou retenção zero                  |
| Não versionar o embedder                  | Impossível reproduzir             | `embedding_model` + revisão + hash               |
| Contexto com 10 chunks do mesmo artigo    | Diversidade ruim                  | Deduplicar por `artigo_id`                       |
| Indexar multivector no pgvector           | pgvector não faz MaxSim nativo    | Usar Qdrant no caminho-alvo                      |
| Rodar o 9B em GPU pequena                 | OOM ou swap                       | 24 GB é borderline; 48 GB confortável; fallback  |
| Usar Harrier no índice e pplx na consulta | Espaços diferentes                | Alvo: 9B index / 0.6B query; fallback: Harrier   |

## 12. Checklist de tuning

- [ ] O caminho está registrado: alvo (9B/0.6B) ou fallback (Harrier)?
- [ ] O Qdrant está pinado em uma versão testada?
- [ ] A coleção tem os vetores `late` (max_sim) e `bm25` (idf)?
- [ ] O ID do ponto é `UUIDv5(device_id@norm_version_id)`?
- [ ] O payload tem `norm_version_id`, `vigencia_status`, `vigencia_inicio` e `vigencia_fim`?
- [ ] O índice e a consulta usam o mesmo espaço vetorial?
- [ ] O conjunto de avaliação tem 150 perguntas com IDs corretos?
- [ ] A citação explícita tem caminho direto por ID?
- [ ] O BM25 esparso sozinho já traz citações explícitas?
- [ ] O MaxSim/rerank melhora nDCG sem estourar latência?
- [ ] O filtro de vigência está correto para fatos antigos?
- [ ] A deduplicação ocorre depois do MaxSim, por artigo?
- [ ] A hidratação por `(device_id, norm_version_id)` está implementada?
- [ ] O contexto final tem 10 dispositivos diversos e 6.000 tokens no máximo?
- [ ] A citação é resolvida por ID + versão, não pelo LLM?
- [ ] O modelo, a revisão e o hash do texto estão registrados?
- [ ] O custo por pergunta está dentro do orçamento?

## 13. Testes de componentes

| Teste                        | Fixture                                                       | Asserção                                               |
| ---------------------------- | ------------------------------------------------------------- | ------------------------------------------------------ |
| RRF                          | listas de ranking conhecidas                                  | ordem fundida esperada                                 |
| Normalização                 | tabela da seção 6                                             | entrada → saída                                        |
| Vigência                     | data == início, data == fim, data fora                        | seleciona a versão correta                             |
| Dedupe/expansão              | 3 folhas do mesmo artigo                                      | 1 artigo, melhor score                                 |
| MaxSim                       | 2 dispositivos, pergunta ambígua                              | dispositivo correto no top 1                           |
| Espaço compartilhado 9B/0.6B | 1 dispositivo indexado com 9B, consulta com 0.6B              | top 1 correto (gate antes da indexação completa)       |
| Fallback                     | 20 perguntas                                                  | recall@10 ≥ 0,75 e sem regressão vs. execução anterior |
| Vazio                        | filtro que remove tudo                                        | abstenção, sem erro                                    |
| Dispositivo longo            | literal > `max_length`                                        | split ou falha; nunca truncamento silencioso           |
| Citação explícita            | `art. 7º`, `art. 24-A`, `inciso III`, `alínea b`, inexistente | resolve ou abster                                      |
| Hidratação                   | par `(device_id, norm_version_id)` inexistente no Postgres    | descarta e registra `incomplete_context`               |

## 14. Mapa de implementação

| Etapa                | Arquivo                              | Fase   |
| -------------------- | ------------------------------------ | ------ |
| Ingestão e chunk     | `src/ingest/*`, `src/index/chunk.py` | Fase 1 |
| Embeddings e upsert  | `src/index/embed.py`                 | Fase 2 |
| Busca híbrida        | `src/retrieve/hybrid.py`             | Fase 3 |
| MaxSim/rerank        | `src/retrieve/rerank.py`             | Fase 3 |
| Dedupe/expansão      | `src/retrieve/expand.py`             | Fase 3 |
| Citação e hidratação | `src/retrieve/citations.py`          | Fase 3 |
| Verificação          | `src/generate/verify.py`             | Fase 4 |

`02 §5` e `09 §3` são normativos para limites de arquivos e fases.
