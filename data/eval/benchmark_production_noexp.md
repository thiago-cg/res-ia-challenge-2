# Benchmark produção: Postgres FTS + Qdrant dense

- Gerado em: `2026-11-07T18:55:03.405592+00:00`
- Backend: `postgres-fts+qdrant-dense`
- LLM: `deepseek/deepseek-v4.1-flash-1017`
- Embeddings: `qwen/qwen3-embedding-8b` (4096d)
- Instrução de consulta: `Instruct: Dada uma pergunta jurídica de uma vítima de violência doméstica, recupere o dispositivo legal que a responde. Query:`
- Postgres: 4959 versões, 4938 dispositivos
- Qdrant: `devices_qdrant_dense_current`
- Perguntas: 20
- Commit: `18db3bb426292d29feea80816a64c72c62ca7b56`
- Expansão de consulta: off (ablação)

| Cenário | Recall@10 dispositivo | Recall@10 artigo | Recall/pergunta | MRR@10 | nDCG@10 | Precisão citação | Cobertura citação | Groundedness | Abstenção | Emergência | p50 (ms) | p95 (ms) |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| dense | 0.583 | 0.733 | 0.400 | 0.483 | 0.456 | 0.270 | 0.467 | 1.000 | 1.000 | 1.000 | 11429 | 22836 |
| hybrid | 0.550 | 0.683 | 0.300 | 0.398 | 0.376 | 0.268 | 0.467 | 0.800 | 0.867 | 1.000 | 11052 | 33879 |

## Falhas por cenário

- **dense**: q001, q002, q003, q005, q008, q009, q010
- **hybrid**: q001, q002, q003, q005, q008, q009, q010

## Gate de qualidade (limits padrão do harness)

- **dense**: FALHOU — recall_at_10=0.5833 < 0.8500; recall_per_question=0.4000 < 0.7000; mrr_at_10=0.4833 < 0.6000; ndcg_at_10=0.4556 < 0.7000; citation_precision=0.2700 < 0.9500; citation_coverage=0.4667 < 0.8000; latency_p95_ms=22835.9778 > 8000.0000
- **hybrid**: FALHOU — recall_at_10=0.5500 < 0.8500; recall_per_question=0.3000 < 0.7000; mrr_at_10=0.3983 < 0.6000; ndcg_at_10=0.3762 < 0.7000; citation_precision=0.2683 < 0.9500; citation_coverage=0.4667 < 0.8000; groundedness=0.8000 < 0.9500; latency_p95_ms=33878.5637 > 8000.0000

## Por split

`dev` orientou a escrita das regras de expansão; `test` não. A distância entre os dois mede quanto do número agregado é in-sample.

| Cenário | Split | n | Recall@10 dispositivo | Recall@10 artigo | MRR@10 |
| --- | --- | ---: | ---: | ---: | ---: |
| dense | dev | 10 | 0.567 | 0.767 | 0.600 |
| dense | test | 10 | 0.600 | 0.700 | 0.367 |
| hybrid | dev | 10 | 0.600 | 0.767 | 0.607 |
| hybrid | test | 10 | 0.500 | 0.600 | 0.190 |

## Notas

- `hybrid` usa FTS real do Postgres (`websearch_to_tsquery('portuguese')` sobre `search_text` sem acento, `ts_rank_cd`) + Qdrant dense 4096d, fundidos por RRF k=60.
- `dense` usa somente Qdrant. `gold` hidrata os dispositivos-ouro do Postgres: seu recall, MRR, nDCG e precisão de citação são 1,000 por construção e não medem recuperação.
- `Recall@10 artigo` conta acerto por artigo, porque a spec deduplica por artigo e devolve um dispositivo por artigo; o gold é por dispositivo.
- `Groundedness` é o portão de aceitação ecoado: 1,000 sempre que a resposta é aceita, 0,000 quando é rejeitada.
- `Precisão de citação` divide pelo número de citações que o modelo escolheu, então citar menos infla o número.
- `Emergência` não penaliza falso positivo: só conta casos de emergência.
- Latência inclui rede, Postgres, Qdrant e LLM; com n=20 o p95 é a segunda pior amostra e mistura emergências sem chamada de LLM.
- O conjunto tem 20 perguntas, das quais 10 são respondíveis: as médias de recuperação são sobre essas 10.
