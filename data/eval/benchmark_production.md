# Benchmark produção: Postgres FTS + Qdrant dense

- Gerado em: `2026-11-07T16:23:59.788105+00:00`
- Backend: `postgres-fts+qdrant-dense`
- LLM: `deepseek/deepseek-v4.1-flash-1017`
- Embeddings: `qwen/qwen3-embedding-8b` (4096d)
- Instrução de consulta: `Instruct: Dada uma pergunta jurídica de uma vítima de violência doméstica, recupere o dispositivo legal que a responde. Query:`
- Postgres: 4959 versões, 4938 dispositivos
- Qdrant: `devices_qdrant_dense_current`
- Perguntas: 20
- Commit: `6607cb08e3b577894d70e2f2f69f5d1c66f5b59b`

| Cenário | Recall@10 | Recall/pergunta | MRR@10 | nDCG@10 | Precisão citação | Cobertura citação | Groundedness | Abstenção | Emergência | p50 (ms) | p95 (ms) |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| dense | 0.583 | 0.400 | 0.483 | 0.456 | 0.243 | 0.533 | 1.000 | 1.000 | 1.000 | 11155 | 21570 |
| hybrid | 0.583 | 0.400 | 0.458 | 0.438 | 0.273 | 0.467 | 0.900 | 0.933 | 1.000 | 12017 | 31016 |
| gold | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 0.967 | 1.000 | 1.000 | 1.000 | 0 | 19216 |

## Falhas por cenário

- **dense**: q002, q003, q005, q008, q009, q010
- **hybrid**: q001, q002, q003, q005, q008, q009, q010
- **gold**: q001

## Notas

- `hybrid` usa FTS real do Postgres (`websearch_to_tsquery('portuguese')`, `ts_rank_cd`) + Qdrant dense 4096d, fundidos por RRF.
- `dense` usa somente Qdrant; `gold` entrega os dispositivos-ouro hidratados do Postgres e mede geração/citação, não recuperação.
- O Qdrant usa HNSW aproximado; a latência inclui rede, Postgres, Qdrant e LLM.
