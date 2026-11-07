# Benchmark produção: Postgres FTS + Qdrant dense

- Gerado em: `2026-11-07T15:21:00.250343+00:00`
- Backend: `postgres-fts+qdrant-dense`
- LLM: `deepseek/deepseek-v4.1-flash-1017`
- Embeddings: `qwen/qwen3-embedding-8b` (4096d)
- Instrução de consulta: `Instruct: Dada uma pergunta jurídica de uma vítima de violência doméstica, recupere o dispositivo legal que a responde. Query:`
- Postgres: 4959 versões, 4938 dispositivos
- Qdrant: `devices_qdrant_dense_current`
- Perguntas: 20
- Commit: `d3544f2de02d5241b06a5a0490724fd4c865d8db`

| Cenário | Recall@10 | Recall/pergunta | MRR@10 | nDCG@10 | Precisão citação | Cobertura citação | Groundedness | Abstenção | Emergência | p50 (ms) | p95 (ms) |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| dense | 0.583 | 0.400 | 0.458 | 0.438 | 0.227 | 0.533 | 1.000 | 1.000 | 1.000 | 7698 | 26246 |
| hybrid | 0.583 | 0.400 | 0.458 | 0.438 | 0.227 | 0.533 | 0.900 | 0.933 | 1.000 | 7489 | 21396 |
| gold | 1.000 | 1.000 | 1.000 | 1.000 | 0.900 | 0.900 | 0.900 | 0.933 | 1.000 | 0 | 8545 |

## Falhas por cenário

- **dense**: q002, q003, q005, q008, q009, q010
- **hybrid**: q001, q002, q003, q005, q008, q009, q010
- **gold**: q008

## Notas

- `hybrid` usa FTS real do Postgres (`websearch_to_tsquery('portuguese')`, `ts_rank_cd`) + Qdrant dense 4096d, fundidos por RRF.
- `dense` usa somente Qdrant; `gold` entrega os dispositivos-ouro hidratados do Postgres e mede geração/citação, não recuperação.
- O Qdrant usa HNSW aproximado; a latência inclui rede, Postgres, Qdrant e LLM.
