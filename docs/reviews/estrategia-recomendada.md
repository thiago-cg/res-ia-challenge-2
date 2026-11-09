# Estratégia recomendada (canônica)

Esta é a página única da estratégia de recuperação. Quem for mudar um destes
valores deve ler as seções "Por quê" e "Como revalidar" abaixo.
Evidência completa em [benchmark-consolidado.md](benchmark-consolidado.md);
raciocínio em [decisoes-benchmark-2026-11.md](decisoes-benchmark-2026-11.md).

## Decisão

| camada | valor | onde |
| --- | --- | --- |
| Unidade indexada | dispositivo (`device_id`) | `src/index/chunk.py` |
| Texto indexado | `contexto` determinístico + `texto_literal` | `src/index/chunk.py` |
| Caminho | `retrieval_path=fallback` | `src/config.py` |
| Denso | Qdrant, `qwen3-embedding-8b` 4096d, cosseno, float16 | `src/index/qdrant.py` |
| Lexical | Postgres FTS, escore por IDF | `src/index/pgvector.py` |
| Fusão | RRF, `k`=60, peso lexical **0,2** | `src/retrieve/hybrid.py` |
| Expansão de consulta | regras determinísticas, **ligada** | `src/retrieve/query.py` |
| Teto por artigo | **3**, preservando a ordem global | `src/retrieve/expand.py` |
| Reranker | **desligado** | `src/retrieve/llm_rerank.py` |
| Reescrita por LLM | **desligada** | `src/retrieve/query.py` |
| Risco/emergência | classificador determinístico, 3 camadas | `src/safety/risk.py` |
| Verificação | determinística, sem LLM juiz | `src/generate/verify.py` |

Valores em `Settings()`: `hybrid_lexical_weight=0.2`,
`max_devices_per_article=3`, `rerank_provider="none"`,
`query_expansion=True`, `query_rewrite="none"`, `llm_max_tokens=0`.
Estão travados por [tests/unit/test_recommended_strategy.py](../../tests/unit/test_recommended_strategy.py).

## Por quê

### O topo da tabela é empate, então o desempate não é acurácia

| configuração | recall@10 |
| --- | ---: |
| denso, sem teto | 0,776 |
| híbrido, sem teto | 0,771 |
| denso, teto 3, ordem preservada | 0,767 |
| **híbrido, teto 3, ordem preservada (escolhida)** | **0,762** |

Com 110 perguntas, o erro-padrão de uma proporção em torno de 0,77 é da ordem de
3 a 4 pontos (aproximação binomial; o valor real é menor porque o recall é média
de frações por pergunta). A distância de 1,4 ponto entre a primeira e a quarta
configuração é ruído, não sinal. Já as decisões que importam estão a 3 ou 5
erros-padrão de distância:

| mudança | efeito | magnitude |
| --- | ---: | ---: |
| dedupe preservando a ordem | +11,4 pts | ~3x |
| expansão determinística | +13 pts | ~3,5x |
| doc2query | −21 pts | ~5x |
| reescrita por LLM | −22 pts | ~5x |
| reranker LLM (contrato por dispositivo) | −20 pts | ~5x |

### Os três desempates que a métrica não vê

1. **Degradação graciosa.** A perna lexical entrega **0,414 sozinha**. Se o
   provedor de embedding cair, o sistema continua respondendo. O denso puro
   devolve zero. Nesta rodada o provedor caiu de fato.
2. **Contexto limitado.** Sem teto, os dez slots podem ser preenchidos por
   parágrafos do mesmo artigo. Com teto 3, a resposta mostra diversidade de
   normas, que é o que a usuária precisa ler.
3. **Determinismo.** Nenhum LLM no caminho da consulta: mesma pergunta, mesma
   recuperação, auditável. Isso é requisito de LGPD/auditoria do projeto, não
   preferência estética.

### A tese

> Tudo que adiciona julgamento de LLM no laço perdeu. Tudo que adiciona
> estrutura determinística da lei ganhou.

Ganharam: vocabulário jurídico curado na consulta, hierarquia legal no chunk,
preservação de ordem no dedupe, teto por artigo, filtro de vigência.
Perderam: reescrita por LLM (−22), HyDE (−20), subperguntas (−18), acréscimo de
termos (−20), reranker LLM (−20), doc2query (−21), contexto enriquecido (−10).

A explicação não é "LLM é ruim". É que o modelo **substitui** a pergunta da
vítima por vocabulário jurídico genérico, apagando o detalhe que discriminava o
artigo; as regras curadas **acrescentam** a ela.

## Onde a resposta muda: o contrato de citação

| contrato | melhor estratégia | métrica |
| --- | --- | --- |
| **dispositivo (atual)** | híbrida, sem reranker | dispositivo@10 0,762 |
| artigo | híbrida **com reranker LLM** | artigo@10 **0,873**, MRR 0,519 |

O reranker LLM acerta mais o artigo que qualquer outra configuração e cita a
linha do artigo em vez do parágrafo. Se o contrato migrar para citação por
artigo, ele passa a ser a escolha certa — mas as duas coisas têm de mudar
juntas, senão o recall por dispositivo cai 20 pontos.

## O que não fazer

Reindexação para doc2query · chunking semântico ou dinâmico · reescrita, HyDE ou
subperguntas por LLM · reranker com contrato por dispositivo · peso lexical alto
(1,0 derruba para 0,576) · enriquecimento volumétrico do chunk · LLM juiz ligado
por padrão (derrubou o `groundedness` para 0,100 numa rodada anterior por
truncamento de JSON).

## Como revalidar

```powershell
# 1. recuperação: todas as famílias, uma passada de embedding só
python scripts/sweep_retrieval.py --database-url $env:DATABASE_URL --qdrant-url $env:QDRANT_URL

# 2. consulta e reranking com o provedor fixo
python scripts/sweep_llm.py    --database-url $env:DATABASE_URL --qdrant-url $env:QDRANT_URL
python scripts/sweep_rerank.py --database-url $env:DATABASE_URL --qdrant-url $env:QDRANT_URL

# 3. ponta a ponta
python scripts/benchmark_e2e.py --database-url $env:DATABASE_URL --qdrant-url $env:QDRANT_URL
```

Os resultados ficam em `data/eval/sweep_*.json` e `data/eval/benchmark_e2e_*.json`.
Se um número mudar além do ruído, atualize esta página no mesmo commit.

## Limites

As 110 perguntas respondíveis compartilham **16 dispositivos-ouro em 15
artigos**; o número compara estratégias entre si e não mede cobertura de tema.
Não há avaliação humana. `citation_precision` mede aderência ao gabarito, não
alucinação ([detalhe](metodologia-avaliacao.md)).
