# Benchmark produção: Postgres FTS + Qdrant dense

- Gerado em: `2026-11-07T16:56:46.343911+00:00`
- Backend: `postgres-fts+qdrant-dense`
- LLM: `deepseek/deepseek-v4.1-flash-1017`
- Embeddings: `qwen/qwen3-embedding-8b` (4096d)
- Instrução de consulta: `Instruct: Dada uma pergunta jurídica de uma vítima de violência doméstica, recupere o dispositivo legal que a responde. Query:`
- Postgres: 4959 versões, 4938 dispositivos
- Qdrant: `devices_qdrant_dense_current`
- Perguntas: 20
- Commit: `b8ed46364f5f272a9f29efaa903c142dcddfd843`

| Cenário | Recall@10 | Recall/pergunta | MRR@10 | nDCG@10 | Precisão citação | Cobertura citação | Groundedness | Abstenção | Emergência | p50 (ms) | p95 (ms) |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| dense | 0.850 | 0.700 | 0.617 | 0.644 | 0.468 | 0.750 | 1.000 | 1.000 | 1.000 | 8464 | 47460 |
| hybrid | 0.850 | 0.700 | 0.600 | 0.626 | 0.435 | 0.650 | 1.000 | 1.000 | 1.000 | 8265 | 61081 |
| gold | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 0.950 | 1.000 | 1.000 | 1.000 | 0 | 21044 |

## Falhas por cenário

- **dense**: q001, q003, q005, q009, q010
- **hybrid**: q001, q003, q005, q008, q009, q010
- **gold**: q003

## Notas

- `hybrid` usa FTS real do Postgres (`websearch_to_tsquery('portuguese')`, `ts_rank_cd`) + Qdrant dense 4096d, fundidos por RRF.
- `dense` usa somente Qdrant; `gold` entrega os dispositivos-ouro hidratados do Postgres e mede geração/citação, não recuperação.
- O Qdrant usa HNSW aproximado; a latência inclui rede, Postgres, Qdrant e LLM.
