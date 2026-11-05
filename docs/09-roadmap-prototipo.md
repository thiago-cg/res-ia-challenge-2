# 09 — Roadmap do protótipo

> Plano executável consolidado: [`10-plano-implementacao.md`](10-plano-implementacao.md). Este roadmap resume as fases; o documento 10 é a fonte das tasks, arquivos, dependências e gates.

## 1. Objetivo do dia

Entregar um protótipo local que:

1. ingere o núcleo legal;
2. indexa dispositivos com IDs e vigência;
3. recupera por busca híbrida;
4. responde com citação resolvida por ID;
5. abstém-se quando não sabe;
6. trata emergência antes do RAG;
7. passa em 20 perguntas de teste.

## 2. Escopo do MVP

### Entra

- Lei Maria da Penha completa.
- Artigos selecionados do CP e do CPP (crimes, prazos, ação penal).
- Lei 15.438/2026.
- Súmulas 542 e 600 do STJ.
- Resolução Conjunta CNJ/CNMP nº 5/2020.
- Busca híbrida (multivector + BM25 esparso) no alvo; denso + FTS no fallback.
- Versões por dispositivo e filtro por data do fato.
- MaxSim no Qdrant (alvo) ou rerank opcional (fallback).
- Resolvedor de citação.
- Verificador.
- Roteador de risco.
- UI simples.
- 20 perguntas de avaliação.

### Não entra

- Grafo completo de remissões.
- Doc2query em todos os dispositivos.
- Acórdãos completos.
- Doutrina do Jusbrasil.
- Fine-tuning.
- Loop agêntico com muitas ferramentas.
- Atendimento por voz/WhatsApp.
- Integração com sistemas externos.

## 3. Fases

### Fase 0 — Setup (1–2 h)

| Tarefa                     | Entrega                          | Aceite                                   |
| -------------------------- | -------------------------------- | ---------------------------------------- |
| Criar `docker-compose.yml` | Postgres + Qdrant (alvo)         | `docker compose up -d` sobe o alvo       |
| Criar projeto Python       | `pyproject.toml`, `.env.example` | `uv sync` ou `pip install -e .` funciona |
| Criar schema               | migration SQL                    | Tabelas de versões e extensões criadas   |
| Criar API mínima           | `/health`                        | Retorna status do banco                  |

### Fase 1 — Ingestão (3–4 h)

| Tarefa           | Entrega                    | Aceite                                   |
| ---------------- | -------------------------- | ---------------------------------------- |
| Baixar fontes P0 | `data/raw/*.html` + hashes | URLs oficiais, bytes salvos              |
| Parser Planalto  | `parse_planalto.py`        | LMP parseada em árvore                   |
| Parser CNJ       | `parse_cnj.py`             | Resolução 5/2020 parseada                |
| Parser súmulas   | `parse_sumulas.py`         | Súmulas 542 e 600                        |
| Normalizador     | `normalize.py`             | Sem texto riscado; citações normalizadas |
| Carga no banco   | `load_db.py`               | Dispositivos com IDs únicos              |
| Validação        | script                     | Contagem e amostra conferidas            |

**Atalho:** se o parser do CP/CPP atrasar, ingerir apenas os artigos necessários, colados de fonte oficial, com o mesmo schema.

### Fase 2 — Índice (2–3 h)

| Tarefa                | Entrega         | Aceite                                                                                      |
| --------------------- | --------------- | ------------------------------------------------------------------------------------------- |
| Popular `search_text` | script          | Texto normalizado para FTS                                                                  |
| Indexar multivector   | `embed.py`      | pplx 9B no Qdrant com point ID e payload de versão (alvo) ou Harrier no pgvector (fallback) |
| Criar índices         | SQL/Qdrant      | GIN/HNSW (fallback) e payload indexes (alvo)                                                |
| Testar busca densa    | notebook/script | Top 10 traz dispositivos plausíveis                                                         |
| Testar FTS            | SQL             | "art. 24-A" e "medida protetiva" funcionam                                                  |

**Fallback:** se o download do modelo for lento, começar só com FTS e adicionar embeddings depois. A avaliação inicial pode ser lexical.

### Fase 3 — Recuperação (2–3 h)

| Tarefa                | Entrega        | Aceite                                        |
| --------------------- | -------------- | --------------------------------------------- |
| Normalizar consulta   | `hybrid.py`    | "art. 7º" vira "artigo 7"                     |
| Busca densa + FTS     | `hybrid.py`    | Top 50 de cada                                |
| RRF                   | `hybrid.py`    | Lista fundida                                 |
| Filtro de vigência    | SQL            | Versão correta por data                       |
| Dedup por artigo      | `hybrid.py`    | Sem 10 chunks do mesmo artigo                 |
| Expansão para artigo  | `expand.py`    | Contexto completo                             |
| MaxSim / rerank       | `rerank.py`    | Qdrant MaxSim (alvo) ou pplx/Qwen3 (fallback) |
| Citação explícita     | `citations.py` | "art. 22" resolve direto por ID               |
| Hidratação            | `citations.py` | Texto/citação/explicação vêm do Postgres      |
| Resolvedor de citação | `citations.py` | ID vira citação                               |

### Fase 4 — Geração e segurança (3–4 h)

| Tarefa            | Entrega                   | Aceite                         |
| ----------------- | ------------------------- | ------------------------------ |
| Prompt do sistema | `prompt.py`               | Proíbe invenção e exige IDs    |
| Schema JSON       | `schemas.py`              | Validação com Pydantic         |
| Gerador           | `llm.py`                  | Local ou API com retenção zero |
| Verificador       | `verify.py`               | Rejeita ID desconhecido        |
| Roteador de risco | `risk.py`                 | 190/180 antes do RAG           |
| Abstenção         | `prompt.py` + `verify.py` | Fora do corpus não inventa     |
| UI                | `web/`                    | Chat + cards de citação        |

### Fase 5 — Avaliação (2–3 h)

| Tarefa       | Entrega                     | Aceite                             |
| ------------ | --------------------------- | ---------------------------------- |
| 20 perguntas | `data/eval/questions.jsonl` | IDs corretos                       |
| Harness      | `src/eval/run.py`           | Métricas calculadas                |
| Rodada       | relatório                   | Recall, citação, abstenção         |
| Correções    | commits                     | Falhas principais resolvidas       |
| Revisão      | parecer                     | Advogada/defensora revisou amostra |

## 4. Cronograma sugerido

| Período | Foco                            |
| ------- | ------------------------------- |
| 0–2 h   | Setup, schema, health           |
| 2–6 h   | Ingestão da LMP + súmulas + CNJ |
| 6–9 h   | Índice e busca                  |
| 9–13 h  | Geração, citação, verificação   |
| 13–16 h | UI e emergência                 |
| 16–20 h | Avaliação e correções           |

Se o tempo apertar, cortar nesta ordem:

1. Rerank.
2. Embeddings densos (ficar só com FTS).
3. CP/CPP completo (ficar com artigos selecionados).
4. UI elaborada (usar Streamlit simples).

Nunca cortar:

- roteador de emergência;
- resolvedor de citação;
- verificador;
- abstenção;
- aviso legal.

## 5. Riscos e mitigação

| Risco                          | Probabilidade | Impacto    | Mitigação                                        |
| ------------------------------ | ------------- | ---------- | ------------------------------------------------ |
| Parser do Planalto quebrar     | Alta          | Alto       | Amostra manual + parser por seção                |
| Modelo de embedding não baixar | Média         | Médio      | FTS primeiro; baixar em background               |
| Sem GPU                        | Média         | Alto       | Fallback Harrier/pgvector ou FTS; alvo exige GPU |
| Latência alta                  | Média         | Médio      | Top 20, menos subperguntas, LLM menor            |
| Base incompleta                | Alta          | Alto       | Abstenção e escopo explícito                     |
| Erro jurídico                  | Média         | Muito alto | Revisão humana e casos de regressão              |
| Jusbrasil sem licença          | Certa         | Médio      | Remover doutrina do MVP                          |
| PII em log                     | Média         | Alto       | Logs mínimos e anonimização                      |
| Prompt injection               | Baixa         | Alto       | Texto como dado + testes                         |

## 6. Critérios de aceite

### Técnicos

- [ ] `docker compose up -d` sobe o caminho-alvo (ou `db` para o fallback).
- [ ] `python -m src.ingest.run` ingere as fontes P0.
- [ ] `python -m src.index.run` indexa o multivector no Qdrant (alvo) ou os embeddings no pgvector (fallback).
- [ ] `uvicorn src.api.main:app` sobe a API.
- [ ] `streamlit run web/app.py` sobe a UI.
- [ ] Testes unitários do parser passam.
- [ ] Testes do resolvedor de citação (ID + versão) passam.
- [ ] Testes do roteador de risco passam.
- [ ] Teste de vigência por data do fato passa.
- [ ] Smoke test 9B/0.6B (indexa 1, consulta 1) passa antes da indexação completa.

### Funcionais

- [ ] "Ele pode ser proibido de me mandar mensagem?" cita `lmp/art22/cpt/inc3/ali-b`.
- [ ] "Preciso de boletim para pedir medida protetiva?" cita `lmp/art19/par5`.
- [ ] "O que diz o art. 22?" resolve direto por ID, sem depender da busca híbrida.
- [ ] "Ainda dá tempo de denunciar?" cita a regra de 12 meses com ressalva de data.
- [ ] "Ele está me batendo agora" aciona 190/180 antes do RAG.
- [ ] Pergunta fora do corpus abstém e encaminha.
- [ ] Nenhuma resposta cita ID inexistente.

### Qualidade

- [ ] Recall@10 ≥ 0,80 no conjunto semeado.
- [ ] Precisão de citação ≥ 0,95.
- [ ] Groundedness ≥ 0,95.
- [ ] 100% dos casos de emergência corretos.
- [ ] Smoke test 9B/0.6B e teste de vigência aprovados.
- [ ] Revisão humana registrada.

## 7. Próximas iterações

### Iteração 2 — Cobertura e precisão

- Doc2query nos dispositivos núcleo.
- Grafo determinístico de remissões.
- Busca por data em toda a interface.
- Expansão para artigo e caput.
- Conjunto de 150 perguntas.
- Comparação pplx 9B/0.6B vs pplx 0.6B vs Harrier vs Qwen3.

### Iteração 3 — Agente e regras

- Loop agêntico curto com ferramentas fixas.
- Camada de regras para perguntas condicionais.
- CAG do núcleo legal com prompt caching.
- Jurisprudência em Teses do STJ.
- Acórdãos selecionados.

### Iteração 4 — Produção

- UI acessível e responsiva.
- Autenticação e controle de acesso.
- Observabilidade e alertas.
- Backup e restauração.
- Contrato de retenção zero com APIs.
- Auditoria jurídica e de segurança.
- Teste com usuárias e profissionais da rede.

## 8. Definition of done

O protótipo está pronto quando:

1. Um comando sobe o ambiente local.
2. A base é ingerida e versionada.
3. A busca recupera os dispositivos dos 20 casos semeados.
4. A resposta cita apenas IDs recuperados.
5. O verificador bloqueia citação inválida.
6. A emergência é tratada antes do RAG.
7. A abstenção funciona.
8. Há um relatório de avaliação com métricas e falhas.
9. Uma advogada ou defensora revisou a amostra.
10. A documentação permite outra pessoa rodar o projeto.

## 9. Checklist do dia

- [ ] Criar repositório e estrutura de pastas.
- [ ] Subir Postgres + Qdrant (alvo) ou só Postgres (fallback).
- [ ] Baixar LMP, CP, CPP, súmulas e CNJ.
- [ ] Parsear a LMP.
- [ ] Parsear súmulas e CNJ.
- [ ] Carregar dispositivos no banco.
- [ ] Popular FTS.
- [ ] Indexar multivector com pplx 9B (alvo) ou embeddings com Harrier (fallback).
- [ ] Implementar busca híbrida.
- [ ] Implementar resolvedor de citação.
- [ ] Implementar prompt e schema.
- [ ] Implementar verificador.
- [ ] Implementar roteador de risco.
- [ ] Montar UI.
- [ ] Criar 20 perguntas de avaliação.
- [ ] Rodar avaliação.
- [ ] Corrigir as 3 falhas principais.
- [ ] Escrever relatório final.
- [ ] Pedir revisão jurídica.
