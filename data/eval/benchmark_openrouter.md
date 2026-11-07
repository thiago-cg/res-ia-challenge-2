# Benchmark OpenRouter

- Gerado em: `2026-11-07T02:50:58.592219+00:00`
- LLM: `deepseek/deepseek-v4.1-flash-1017`
- Embeddings: `qwen/qwen3-embedding-8b` (4096d)
- Corpus: 9376 dispositivos
- Perguntas: 20

| Cenário | Recall@10 | Recall/pergunta | MRR@10 | nDCG@10 | Precisão citação | Cobertura citação | Groundedness | Abstenção | Emergência | p50 (ms) | p95 (ms) |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| dense | 0.450 | 0.300 | 0.381 | 0.331 | 0.220 | 0.417 | 1.000 | 0.867 | 1.000 | 10364 | 18982 |
| hybrid | 0.450 | 0.200 | 0.190 | 0.239 | 0.223 | 0.417 | 0.800 | 0.800 | 1.000 | 9481 | 24019 |
| gold | 1.000 | 1.000 | 1.000 | 1.000 | 0.900 | 0.900 | 0.900 | 0.933 | 1.000 | 0 | 26695 |

## Falhas por cenário

- **dense**: q001, q002, q003, q005, q006, q008, q009, q010, q017, q019
- **hybrid**: q001, q002, q003, q004, q005, q008, q009, q010, q019
- **gold**: q008

## Notas

- **gold** é contexto-ouro: recall@10, MRR e nDCG são 1,0 por construção; ele mede geração/citação, não recuperação.
- A latência inclui rede e LLM; no cenário gold, emergência e fora do corpus não chamam o LLM, por isso o p50 pode ser 0 ms.
- O corpus é local (`data/processed` não versionado), gerado pela ingestão das fontes oficiais; o fingerprint identifica a execução.
- Harness em memória: BM25 aproximado (não é o FTS português do Postgres) e vetores em RAM. Não é o caminho de produção.
