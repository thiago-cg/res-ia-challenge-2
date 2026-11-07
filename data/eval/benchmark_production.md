# Benchmark produção: Postgres FTS + Qdrant dense

- Gerado em: `2026-11-07T22:23:48.832833+00:00`
- Backend: `postgres-fts+qdrant-dense`
- LLM: `deepseek/deepseek-v4.1-flash-1017`
- Embeddings: `qwen/qwen3-embedding-8b` (4096d)
- Instrução de consulta: `Instruct: Dada uma pergunta jurídica de uma vítima de violência doméstica, recupere o dispositivo legal que a responde. Query:`
- Postgres: 4959 versões, 4938 dispositivos
- Qdrant: `devices_qdrant_dense_current`
- Perguntas: 20
- Commit: `87eae46fa62432cb3221586221a1f9862f2c1ba8`
- Expansão de consulta: on

| Cenário | Recall@10 dispositivo | Recall@10 artigo | Recall/pergunta | MRR@10 | nDCG@10 | Precisão citação | Cobertura citação | Groundedness | Abstenção | Emergência | p50 (ms) | p95 (ms) |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| dense | 1.000 | 1.000 | 1.000 | 0.565 | 0.649 | 0.313 | 0.817 | 1.000 | 0.933 | 1.000 | 12771 | 25572 |
| hybrid | 0.950 | 1.000 | 0.900 | 0.599 | 0.645 | 0.388 | 0.833 | 0.800 | 0.867 | 1.000 | 8786 | 367274 |
| gold | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 0.900 | 0.817 | 0.900 | 0.933 | 1.000 | 0 | 16084 |

## Falhas por cenário

- **dense**: q001, q008, q010, q019
- **hybrid**: q001, q002, q008, q009, q010
- **gold**: q003, q008, q009

## Gate de qualidade (limits padrão do harness)

- **dense**: FALHOU — mrr_at_10=0.5650 < 0.6000; ndcg_at_10=0.6494 < 0.7000; citation_precision=0.3133 < 0.9500; latency_p95_ms=25572.1728 > 8000.0000
- **hybrid**: FALHOU — mrr_at_10=0.5992 < 0.6000; ndcg_at_10=0.6447 < 0.7000; citation_precision=0.3883 < 0.9500; groundedness=0.8000 < 0.9500; latency_p95_ms=367274.4164 > 8000.0000
- **gold**: FALHOU — citation_precision=0.9000 < 0.9500; groundedness=0.9000 < 0.9500; latency_p95_ms=16083.6893 > 8000.0000

## Por split

`dev` orientou a escrita das regras de expansão; `test` não. A distância entre os dois mede quanto do número agregado é in-sample.

| Cenário | Split | n | Recall@10 dispositivo | Recall@10 artigo | MRR@10 |
| --- | --- | ---: | ---: | ---: | ---: |
| dense | dev | 10 | 1.000 | 1.000 | 0.867 |
| dense | test | 10 | 1.000 | 1.000 | 0.263 |
| hybrid | dev | 10 | 1.000 | 1.000 | 0.867 |
| hybrid | test | 10 | 0.900 | 1.000 | 0.332 |
| gold | dev | 10 | 1.000 | 1.000 | 1.000 |
| gold | test | 10 | 1.000 | 1.000 | 1.000 |

## Notas

- `hybrid` usa FTS real do Postgres (`websearch_to_tsquery('portuguese')` sobre `search_text` sem acento, `ts_rank_cd`) + Qdrant dense 4096d, fundidos por RRF k=60.
- `dense` usa somente Qdrant. `gold` hidrata os dispositivos-ouro do Postgres: seu recall, MRR, nDCG e precisão de citação são 1,000 por construção e não medem recuperação.
- `Recall@10 artigo` conta acerto por artigo, porque a spec deduplica por artigo e devolve um dispositivo por artigo; o gold é por dispositivo.
- `Groundedness` é o portão de aceitação ecoado: 1,000 sempre que a resposta é aceita, 0,000 quando é rejeitada.
- `Precisão de citação` divide pelo número de citações que o modelo escolheu, então citar menos infla o número.
- `Emergência` não penaliza falso positivo: só conta casos de emergência.
- Latência inclui rede, Postgres, Qdrant e LLM; com n=20 o p95 é a segunda pior amostra e mistura emergências sem chamada de LLM.
- O conjunto tem 20 perguntas, das quais 10 são respondíveis: as médias de recuperação são sobre essas 10.
