# Benchmark end-to-end

- Gerado em: 2026-11-09T14:41:43.131488+00:00
- Modelo: deepseek/deepseek-v4.1-flash-1017 (provedor deepinfra/fp8)
- Embeddings: qwen/qwen3-embedding-8b (4096d)
- Perguntas: 150

| cenario | recall@10 | artigo@10 | cit. cobertura | groundedness | abstenção | emergência | p50 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| hybrid | 0.762 | 0.826 | 0.617 | 0.909 | 0.923 | 0.750 | 24494 ms |
