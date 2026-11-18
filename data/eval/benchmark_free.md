# Benchmark de produção: FTS + busca densa

- Gerado em: `2026-11-18T17:54:30.850958+00:00`
- Backend: `postgres-fts+pgvector`
- LLM: `openrouter/free`
- Embeddings: `qwen/qwen3-embedding-8b` (1024d)
- Índice vetorial: pgvector (coluna `vector(1024)`)
- Instrução de consulta: `Instruct: Dada uma pergunta jurÃ­dica de uma vÃ­tima de violÃªncia domÃ©stica, recupere o dispositivo legal que a responde. Query:`
- Postgres: 10797 versões, 10548 dispositivos
- Perguntas: 150
- Commit: `e88b526f7ab8c027d92ce59ec17cbf7dcbb904af`
- Expansão de consulta: on
- Intervalo mínimo entre chamadas: 20 s (~3 RPM)

| Cenário | Recall@10 dispositivo | Recall@10 artigo | Recall/pergunta | MRR@10 | nDCG@10 | Precisão citação | Cobertura citação | Groundedness | Abstenção | Emergência | p50 (ms) | p95 (ms) |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| hybrid | 0.624 | 0.720 | 0.482 | 0.414 | 0.426 | 0.265 | 0.486 | 0.745 | 0.754 | 1.000 | 29990 | 154494 |

## Falhas por cenário

- **hybrid**: q001, q006, q008, q010, q016, q017, q021, q022, q023, q024, q025, q026, q028, q029, q030, q032, q033, q035, q036, q037, q038, q039, q040, q041, q042, q043, q044, q045, q046, q047, q049, q050, q056, q057, q061, q063, q065, q067, q068, q070, q071, q072, q073, q074, q075, q076, q077, q078, q079, q080, q081, q082, q083, q085, q087, q091, q092, q093, q094, q095, q096, q097, q098, q099, q100, q101, q102, q103, q104, q105, q106, q107, q108, q109, q110, q111, q112, q113, q114, q115, q116, q117, q118, q119, q120, q129, q133

## Gate de qualidade (limits padrão do harness)

- **hybrid**: FALHOU — recall_at_10=0.6242 < 0.8500; recall_per_question=0.4818 < 0.7000; mrr_at_10=0.4136 < 0.6000; ndcg_at_10=0.4265 < 0.7000; citation_precision=0.2654 < 0.9500; citation_coverage=0.4864 < 0.8000; groundedness=0.7455 < 0.9500; abstention_accuracy=0.7538 < 0.8000; latency_p95_ms=154494.4798 > 8000.0000

## Por split

`dev` orientou a escrita das regras de expansão; `test` não. A distância entre os dois mede quanto do número agregado é in-sample.

| Cenário | Split | n | Recall@10 dispositivo | Recall@10 artigo | MRR@10 |
| --- | --- | ---: | ---: | ---: | ---: |
| hybrid | dev | 75 | 0.615 | 0.715 | 0.407 |
| hybrid | test | 75 | 0.633 | 0.724 | 0.420 |

## Notas

- `hybrid` usa FTS real do Postgres (`websearch_to_tsquery('portuguese')` sobre `search_text` sem acento, `ts_rank_cd`) + busca densa no índice vetorial, fundidos por RRF k=60.
- `Recall@10` é por dispositivo: uma pergunta com 2 ou 3 dispositivos-ouro que recupera só um deles marca 0,5, não 1,0. Não é o mesmo número que `hit@k` (acertou algum).
- `Recall@10 artigo` conta acerto por artigo, porque a spec deduplica por artigo; o gold é por dispositivo.
- `Groundedness` é o portão de aceitação ecoado: 1,000 sempre que a resposta é aceita, 0,000 quando é rejeitada.
- `Precisão de citação` divide pelo número de citações que o modelo escolheu, então citar menos infla o número.
- `Emergência` não penaliza falso positivo: só conta casos de emergência.
- A recuperação não depende do gerador: com `QUERY_REWRITE=none` e `RERANK_PROVIDER=none`, a lista de dispositivos é a mesma entre modelos. O que muda com o modelo é aceitação, cobertura de citação e latência.
- Latência inclui rede, Postgres, índice vetorial e LLM; o p95 é a cauda das chamadas reais.
- Para medir com camada gratuita e cota: `--model openrouter/free --min-interval 20` (3 RPM).
