# Protótipo RAG Jurídico — Plano de Implementação Consolidado

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. **Neste runtime, a delegação de subagentes está falhando; a execução recomendada é nativa até o runtime ser corrigido.**

**Goal:** entregar um protótipo local de assistente jurídica com RAG, citação por ID, versionamento por data e roteamento de emergência, começando pelo fallback sem GPU e deixando o caminho 9B/Qdrant pronto para ligar.

**Architecture:** Postgres 17 + pgvector como fonte da verdade; Qdrant v1.15.3 para o alvo multivector; chunking estrutural por dispositivo; `device_versions` como única fonte de texto por vigência; recuperação BM25/MaxSim no alvo e denso/FTS/RRF no fallback; geração com IDs e verificador.

**Tech Stack:** Python 3.12, FastAPI, Streamlit, PostgreSQL 17 + pgvector, Qdrant v1.15.3, sentence-transformers, pplx-embed-v2-late 9B/0.6B, Harrier-OSS-v1-0.6B, Docker Compose.

**Spec:** `docs/README.md`, `docs/01-visao-e-escopo.md` a `docs/09-roadmap-prototipo.md`; este documento é a fonte executável.

**Status:** implementação avançada no caminho fallback em 2026-11-05, com
métricas e revisão jurídica **PENDENTES**. Não há Docker, Postgres ou Qdrant ao
vivo no ambiente de verificação; os artefatos locais de modelo são **GGUF** e não
servem ao caminho alvo, que exige **safetensors**. Nenhum número de avaliação foi
produzido e os gates G4/G6 não foram atingidos.

---

## 0. Como usar este plano

1. Leia `docs/README.md` e `docs/01` a `docs/09` antes de codar.
2. Execute as tasks na ordem das dependências, não na ordem numérica.
3. Cada task é um ciclo TDD: escrever teste que falha, implementar o mínimo, rodar o teste, commit.
4. Uma task só termina quando o teste/aceite passa e a documentação afetada foi atualizada.
5. O caminho padrão é **fallback** (`RETRIEVAL_PATH=fallback`), com LLM mock nos testes. O alvo 9B/Qdrant fica atrás de flag e só entra depois do smoke test.
6. Nenhuma task pode introduzir citação escrita pelo LLM, PII em log ou scraping do Jusbrasil.

## 1. Escopo

### Entra no MVP

- LMP completa; artigos selecionados do CP/CPP; Lei 15.438/2026; Súmulas 542 e 600 do STJ; Resolução Conjunta CNJ/CNMP nº 5/2020.
- Chunking estrutural, IDs, versões por data, citação resolvida por ID.
- Busca fallback (denso + FTS + RRF) e busca alvo (BM25 + MaxSim).
- Geração com IDs, verificador, abstenção, emergência antes do RAG.
- 20 perguntas semeadas + regressões legais.
- UI Streamlit e API FastAPI.

### Não entra no MVP

- Grafo completo de remissões, doc2query em massa, acórdãos completos, doutrina do Jusbrasil, fine-tuning, loop agêntico amplo, voz/WhatsApp.

## 2. Decisões congeladas

| #   | Decisão                                                        | Efeito no código                                          |
| --- | -------------------------------------------------------------- | --------------------------------------------------------- |
| D1  | Unidade = dispositivo legal                                    | IDs por artigo/caput/parágrafo/inciso/alínea              |
| D2  | `device_versions` é a única fonte de texto                     | `devices` só identidade/estrutura; view `devices_current` |
| D3  | `norm_versions` é evento/proveniência                          | Seleção por `device_versions.vigencia_*`                  |
| D4  | LLM devolve só `device_id` + afirmação                         | Versão anexada pela recuperação, nunca pelo LLM           |
| D5  | Alvo = BM25 top 100/subpergunta → união 150 → MaxSim → top 10  | Qdrant `late` + `bm25`                                    |
| D6  | Fallback = denso + FTS top 50 → RRF → rerank opcional → top 10 | Postgres + pgvector                                       |
| D7  | Citação sempre renderizada pelo sistema                        | `resolve_citation` + verificador                          |
| D8  | Jusbrasil não é raspado                                        | Doutrina fora do MVP                                      |
| D9  | Perguntas não saem da infraestrutura sem retenção zero         | Embedder local; LLM mock/local no padrão                  |
| D10 | Texto literal nunca é truncado                                 | Split por subnós ou falha de ingestão                     |

## 2.1 Restrições globais e Review Focus

### Restrições globais

- `MAX_DEVICES=10`; `MAX_CONTEXT_TOKENS=6000`; `MAX_SUBQUESTIONS=3`; `MAX_AGENT_LOOPS=3`.
- Postgres 17 + pgvector; Qdrant `v1.15.3`; `qdrant-client` fixado após o smoke test.
- Alvo: BM25 top 100 por subpergunta → união 150 → MaxSim → dedupe por artigo → top 10.
- Fallback: denso + FTS top 50 → RRF → rerank opcional → dedupe → top 10.
- LLM nunca escolhe `norm_version_id`; a recuperação anexa a versão.
- Nenhum scraping do Jusbrasil; doutrina fora do MVP.
- Nenhum log de texto integral/PII; retenção zero ou curta.
- Texto literal nunca truncado; split/falha se exceder `max_length`.

### Review Focus

Os cinco modos de falha que mais podem prejudicar uma usuária e onde serão testados:

1. **Data do fato antiga com lei nova** → versão errada. Testes em `RET-03`, `RET-06`, `EVA-03`.
2. **Citação explícita inexistente** → artigo vizinho aceito. Teste em `RET-01`.
3. **Dispositivo maior que `max_length`** → pena/inciso cortado. Testes em `ING-05`, `IDX-01`.
4. **Hidratação com dispositivos de normas/versões diferentes** → texto errado. Teste em `RET-06`.
5. **Mensagem de emergência** → atraso pelo RAG. Teste em `GEN-03`.

## 3. Caminho de desenvolvimento padrão

```text
RETRIEVAL_PATH=fallback
EMBEDDING_PROVIDER=harrier
LLM_PROVIDER=mock          # local para demo; api só com contrato
MAX_DEVICES=10
MAX_CONTEXT_TOKENS=6000
MAX_SUBQUESTIONS=3
MAX_AGENT_LOOPS=3
```

Comandos de referência:

```bash
docker compose up -d db
uv sync --extra dev
uv run python -m src.ingest.run --source lmp
uv run python -m src.index.run --path fallback
uv run uvicorn src.api.main:app --no-access-log
uv run streamlit run web/app.py
uv run pytest -m "not integration"
```

Se o time não usar `uv`, os mesmos comandos funcionam com `python -m venv .venv && pip install -e ".[dev]"`.

## 4. Estrutura de arquivos

```text
.
├── docker-compose.yml
├── pyproject.toml
├── .env.example
├── migrations/
│   └── 001_init.sql
├── data/
│   ├── raw/                  # snapshots com hash
│   ├── processed/            # JSONL de dispositivos
│   ├── sources.yaml
│   └── eval/
│       ├── questions.jsonl
│       └── regressions.jsonl
├── src/
│   ├── config.py
│   ├── contracts.py
│   ├── obs/
│   │   └── logging.py
│   ├── ingest/
│   │   ├── run.py
│   │   ├── fetch.py
│   │   ├── parse_planalto.py
│   │   ├── parse_cnj.py
│   │   ├── parse_sumulas.py
│   │   ├── normalize.py
│   │   ├── validate.py
│   │   └── diff.py
│   ├── index/
│   │   ├── chunk.py
│   │   ├── embed.py
│   │   ├── qdrant.py
│   │   ├── pgvector.py
│   │   ├── load_db.py
│   │   └── run.py
│   ├── retrieve/
│   │   ├── citations.py
│   │   ├── query.py
│   │   ├── hybrid.py
│   │   ├── rerank.py
│   │   ├── expand.py
│   │   ├── hydrate.py
│   │   └── render.py
│   ├── generate/
│   │   ├── prompt.py
│   │   ├── llm.py
│   │   ├── schemas.py
│   │   ├── verify.py
│   │   └── fallback.py
│   ├── safety/
│   │   └── risk.py
│   ├── api/
│   │   ├── main.py
│   │   └── schemas.py
│   └── eval/
│       ├── run.py
│       └── metrics.py
├── web/
│   └── app.py
├── tests/
│   ├── unit/
│   ├── integration/
│   └── fixtures/
└── docs/
```

## 5. Interfaces canônicas

`src/contracts.py`:

```python
from datetime import date
from typing import Literal
from uuid import UUID
from pydantic import BaseModel

DeviceType = Literal["artigo", "caput", "paragrafo", "inciso", "alinea", "item"]
VigenciaStatus = Literal["vigente", "alterado", "revogado", "cancelado", "superado"]

class Device(BaseModel):
    id: str
    norm_id: str
    parent_id: str | None
    artigo_id: str
    tipo: DeviceType
    rotulo: str
    caminho: str
    ordem: int

class DeviceVersion(BaseModel):
    device_id: str
    norm_version_id: int
    texto_literal: str
    texto_anterior: str | None
    contexto: str
    citacao: str
    vigencia_status: VigenciaStatus
    redacao_dada_por: str | None
    vigencia_inicio: date
    vigencia_fim: date | None
    fonte_url: str
    content_hash: str
    qdrant_point_id: UUID
    search_text: str

class RetrievedDevice(BaseModel):
    device_id: str
    norm_version_id: int
    score: float
    source: Literal["explicit", "bm25", "dense", "maxsim"]
    texto_literal: str
    citacao: str

class QueryFacts(BaseModel):
    relacao: Literal["companheiro", "ex-companheiro", "familiar", "outro", "desconhecido"]
    tipo_violencia: list[Literal["fisica", "psicologica", "sexual", "patrimonial", "moral", "vicaria"]]
    urgencia: Literal["imediata", "recente", "passada", "desconhecida"]
    data_fato: date | None
    uf: str | None

class Citation(BaseModel):
    device_id: str
    norm_version_id: int
    citacao: str
    texto: str
    contexto: str
    vigencia: VigenciaStatus
    fonte_url: str

class Answer(BaseModel):
    resposta: str
    citacoes: list[Citation]
    proximos_passos: list[str]
    encaminhamentos: list[dict]
    premissas: list[str]
    nivel_confianca: Literal["alto", "medio", "baixo"]
    abstencao: bool
    motivo_abstencao: str | None
```

Funções que o plano fixa:

```python
def parse_source(path: Path) -> list[DeviceVersion]: ...
def load_versions(versions: list[DeviceVersion]) -> None: ...
def index_target(versions: list[DeviceVersion]) -> IndexReport: ...
def index_fallback(versions: list[DeviceVersion]) -> IndexReport: ...
def resolve_explicit_citation(text: str) -> CitationResolution: ...
def understand_query(text: str, facts: QueryFacts) -> QueryPlan: ...
def retrieve(plan: QueryPlan) -> list[RetrievedDevice]: ...
def hydrate(pairs: list[tuple[str, int]]) -> list[Citation]: ...
def verify(answer: Answer, retrieved: list[RetrievedDevice]) -> VerificationResult: ...
```

## 6. Contratos de dados

- **Postgres:** tabelas de `04`, com `devices` (identidade), `device_versions` (texto/vigência/embedding), `device_explanations`, `device_questions`, `device_relations`, `norm_versions`, `norms`, `ingest_runs`, `eval_questions`; view `devices_current`.
- **Qdrant:** coleção/alias `devices_qdrant_current`; vetor `late` (128, Cosine, max_sim, float16); vetor `bm25` (sparse, idf); payload com `device_id`, `norm_version_id`, `norm_id`, `artigo_id`, `tipo`, `vigencia_status`, `vigencia_inicio`, `vigencia_fim`.
- **Hidratação:** sempre por pares `(device_id, norm_version_id)`; não usar um escalar único.
- **Citação:** `resolve_citation(device_id, version_from_retrieval)`; o LLM não escolhe versão.

## 7. Estratégia de testes

| Camada      | O que testa                                                         | Onde                                     |
| ----------- | ------------------------------------------------------------------- | ---------------------------------------- |
| Unit        | parser, normalização, IDs, citação explícita, RRF, dedupe, verifier | `tests/unit/`                            |
| Integration | migração, ingestão, índice fallback, Qdrant, hidratação, API        | `tests/integration/`                     |
| Evaluation  | recall@10, citação, groundedness, abstenção, emergência, latência   | `src/eval/run.py`                        |
| Safety      | risco, PII, prompt injection, abstenção                             | `tests/unit/test_safety.py`              |
| Target gate | 9B indexa / 0.6B consulta, top-1 correto                            | `tests/integration/test_shared_space.py` |

Fixtures mínimas:

- `lmp_art22.html` com art. 22, III, “b”;
- `sumulas_542_600.pdf`;
- `cnj_rc_5_2020.pdf`;
- `questions.jsonl` com 20 perguntas e IDs;
- `regressions.jsonl` com os casos de 08.

## 8. Task board

Cada task segue TDD: teste que falha → implementação mínima → teste que passa → commit. A coluna “Teste/aceite” é o contrato mínimo; a task só fecha quando ele passa.

Legenda: **S** ≤ 2 h, **M** 2–4 h, **L** 4–8 h.

### Fase 0 — Fundação

| ID     | Task                    | Arquivos                                                         | Depende de | Teste/aceite                                                        | Tam. |
| ------ | ----------------------- | ---------------------------------------------------------------- | ---------- | ------------------------------------------------------------------- | ---- |
| FND-01 | Scaffold do repositório | `pyproject.toml`, `src/`, `tests/`, `.env.example`, `.gitignore` | —          | `pytest` coleta; `ruff check` passa                                 | S    |
| FND-02 | Infra local             | `docker-compose.yml`, `scripts/wait_for_db.py`                   | FND-01     | `docker compose up -d`; `pg_isready`; Qdrant `/healthz`             | S    |
| FND-03 | Migração inicial        | `migrations/001_init.sql`                                        | FND-02     | migração aplica em banco vazio; view `devices_current`; constraints | M    |
| FND-04 | Contratos e config      | `src/contracts.py`, `src/config.py`                              | FND-01     | testes de validação; defaults fallback/mock; sem segredos           | S    |
| FND-05 | CI e qualidade          | `.github/workflows/ci.yml`, `ruff.toml`                          | FND-01     | CI roda lint, typecheck e pytest                                    | S    |

### Fase 1 — Ingestão

| ID     | Task                   | Arquivos                                                        | Depende de     | Teste/aceite                               | Tam. |
| ------ | ---------------------- | --------------------------------------------------------------- | -------------- | ------------------------------------------ | ---- |
| ING-01 | Manifesto e downloader | `data/sources.yaml`, `src/ingest/fetch.py`, `src/ingest/run.py` | FND-04         | baixa P0; hash; idempotente; timeout       | M    |
| ING-02 | Parser Planalto        | `src/ingest/parse_planalto.py`, `tests/unit/test_planalto.py`   | ING-01         | LMP art. 22 III “b”; sem riscado; contagem | L    |
| ING-03 | Parser CNJ e súmulas   | `parse_cnj.py`, `parse_sumulas.py`, tests                       | ING-01         | Res. 5/2020; Súmulas 542/600; status       | M    |
| ING-04 | Normalização           | `src/ingest/normalize.py`, tests                                | ING-02, ING-03 | fixtures de citação; `search_text`         | M    |
| ING-05 | Loader e validação     | `src/index/load_db.py`, `src/ingest/validate.py`, tests         | FND-03, ING-04 | upsert idempotente; checklist de 04        | M    |
| ING-06 | Diff e reindexação     | `src/ingest/diff.py`, tests                                     | ING-05         | mudar 1 dispositivo cria 1 versão nova     | M    |

### Fase 2 — Índice

| ID     | Task                  | Arquivos                                                     | Depende de     | Teste/aceite                                    | Tam. |
| ------ | --------------------- | ------------------------------------------------------------ | -------------- | ----------------------------------------------- | ---- |
| IDX-01 | Chunker estrutural    | `src/index/chunk.py`, tests                                  | ING-02, ING-03 | IDs, parent, artigo, citação, contexto          | M    |
| IDX-02 | Embeddings            | `src/index/embed.py`, tests                                  | FND-04, IDX-01 | mock de dimensão; alvo/fallback; revisão fixada | M    |
| IDX-03 | Qdrant                | `src/index/qdrant.py`, integration test                      | IDX-02, FND-02 | point ID UUIDv5; payload; top-1 fixture         | M    |
| IDX-04 | pgvector/FTS          | `src/index/pgvector.py`, tests                               | IDX-02, FND-03 | denso/FTS; HNSW/GIN                             | M    |
| IDX-05 | CLI de índice e smoke | `src/index/run.py`, `tests/integration/test_shared_space.py` | IDX-03, IDX-04 | indexa seed; smoke 9B/0.6B (skip sem GPU)       | M    |

### Fase 3 — Recuperação

| ID     | Task                     | Arquivos                                      | Depende de     | Teste/aceite                                          | Tam. |
| ------ | ------------------------ | --------------------------------------------- | -------------- | ----------------------------------------------------- | ---- |
| RET-01 | Citação explícita        | `src/retrieve/citations.py`, tests            | FND-04         | `art. 7º`, `24-A`, `inciso III`; inexistente → abster | M    |
| RET-02 | Entendimento da consulta | `src/retrieve/query.py`, tests                | FND-04         | schema; parse falhou → pergunta crua                  | M    |
| RET-03 | Busca BM25/densa         | `src/retrieve/hybrid.py`, tests               | IDX-03, IDX-04 | top 100; filtro por data; união 150                   | M    |
| RET-04 | MaxSim                   | `src/retrieve/rerank.py`, tests               | IDX-03         | ordenação fixture; top 10                             | M    |
| RET-05 | Dedupe/expansão          | `src/retrieve/expand.py`, tests               | RET-03, RET-04 | 3 folhas → 1 artigo; melhor score                     | S    |
| RET-06 | Hidratação/render        | `src/retrieve/hydrate.py`, `render.py`, tests | RET-05, FND-03 | pares de versões; citação renderizada                 | M    |
| RET-07 | Verificador              | `src/generate/verify.py`, tests               | RET-06         | ID, versão, afirmação; regenerar/abster               | M    |

### Fase 4 — Geração e segurança

| ID     | Task                     | Arquivos                                      | Depende de             | Teste/aceite                                         | Tam. |
| ------ | ------------------------ | --------------------------------------------- | ---------------------- | ---------------------------------------------------- | ---- |
| GEN-01 | Prompt e schema          | `src/generate/prompt.py`, `schemas.py`, tests | RET-07                 | prompt snapshot; JSON; versão não escolhida pelo LLM | M    |
| GEN-02 | Cliente LLM              | `src/generate/llm.py`, tests                  | GEN-01                 | mock; timeout/retry; schema                          | M    |
| GEN-03 | Roteador de risco        | `src/safety/risk.py`, tests                   | FND-04                 | 190/180 antes do RAG; falsos positivos               | M    |
| GEN-04 | Abstenção/encaminhamento | `src/generate/fallback.py`, tests             | GEN-03                 | fora do corpus; sem evidência                        | S    |
| GEN-05 | API e UI                 | `src/api/main.py`, `web/app.py`, tests        | GEN-02, GEN-03, GEN-04 | `/chat`, `/health`, `/sources`; UI                   | L    |

### Fase 5 — Avaliação

| ID     | Task                  | Arquivos                               | Depende de             | Teste/aceite                                           | Tam. |
| ------ | --------------------- | -------------------------------------- | ---------------------- | ------------------------------------------------------ | ---- |
| EVA-01 | 20 perguntas semeadas | `data/eval/questions.jsonl`            | ING-05                 | 20 linhas válidas; IDs revisados                       | S    |
| EVA-02 | Harness               | `src/eval/run.py`, `metrics.py`, tests | EVA-01, RET-07, GEN-05 | recall, citação, abstenção, latência                   | M    |
| EVA-03 | Regressões legais     | `data/eval/regressions.jsonl`, tests   | EVA-02                 | 15.438/2026; 14.550/2023; 542/600; art. 22; CNJ 5/2020 | M    |
| EVA-04 | 150 + revisão humana  | `data/eval/questions.jsonl`, `docs/08` | EVA-02                 | recall@10 ≥ 0,85; citação ≥ 0,95; parecer              | L    |

### Fase 6 — Operação

| ID     | Task                    | Arquivos                                             | Depende de     | Teste/aceite                    | Tam. |
| ------ | ----------------------- | ---------------------------------------------------- | -------------- | ------------------------------- | ---- |
| OPS-01 | Observabilidade e LGPD  | `src/obs/logging.py`, `src/api/middleware.py`, tests | GEN-05         | request ID; sem PII; retenção   | M    |
| OPS-02 | Backup e CI             | `scripts/backup.sh`, `scripts/restore.sh`, CI        | FND-05         | restore drill; CI verde         | M    |
| OPS-03 | Runbook e gate jurídico | `README.md`, `docs/06`, `docs/10`                    | OPS-01, OPS-02 | setup em máquina limpa; parecer | S    |

### 8.1 Checklist de execução

Legenda: `[x]` = aceite executado e verificado no ambiente local; `[~]` =
implementado, não executado no ambiente local; `[ ]` = pendente.

- [x] FND-01 Scaffold
- [~] FND-02 Infra local
- [~] FND-03 Migração inicial
- [x] FND-04 Contratos e config
- [~] FND-05 CI e qualidade
- [~] ING-01 Manifesto e downloader
- [x] ING-02 Parser Planalto
- [x] ING-03 Parser CNJ e súmulas
- [x] ING-04 Normalização
- [~] ING-05 Loader e validação
- [~] ING-06 Diff e reindexação
- [x] IDX-01 Chunker estrutural
- [x] IDX-02 Embeddings
- [~] IDX-03 Qdrant
- [~] IDX-04 pgvector/FTS
- [~] IDX-05 CLI de índice e smoke
- [x] RET-01 Citação explícita
- [x] RET-02 Entendimento da consulta
- [x] RET-03 Busca BM25/densa
- [x] RET-04 MaxSim
- [x] RET-05 Dedupe/expansão
- [x] RET-06 Hidratação/render
- [x] RET-07 Verificador
- [x] GEN-01 Prompt e schema
- [x] GEN-02 Cliente LLM
- [x] GEN-03 Roteador de risco
- [x] GEN-04 Abstenção/encaminhamento
- [x] GEN-05 API e UI
- [x] EVA-01 20 perguntas semeadas
- [x] EVA-02 Harness
- [x] EVA-03 Regressões legais
- [ ] EVA-04 150 + revisão humana
- [ ] OPS-01 Observabilidade e LGPD
- [ ] OPS-02 Backup e CI
- [ ] OPS-03 Runbook e gate jurídico

> Atualização OPS-03 (2026-11-05): as caixas `[x]` têm aceite verificado com
> testes locais (suíte `pytest -m "not integration"`, ruff, format e mypy). As
> caixas `[~]` têm implementação e evidência unitária/estática, mas o aceite
> depende de Docker, Postgres, Qdrant, download real, migração real ou execução
> observada do CI, e **não** foi executado neste ambiente. As caixas `[x]` e
> `[~]` não afirmam funcionamento ponta a ponta.
>
> Permanecem abertas: **EVA-04** (150 perguntas dependem de execução viva e
> revisão humana); **OPS-01** (módulos de log/middleware implementados e
> testados, mas `create_app` ainda não instala os middlewares e não há sink de
> retenção); **OPS-02** (scripts e job de CI prontos, drill não executado aqui);
> **OPS-03** (README/runbook entregues, parecer jurídico **PENDENTE**).
> FND-02, FND-03, FND-05, ING-01, ING-05, ING-06, IDX-03, IDX-04 e IDX-05
> seguem `[~]` até execução real.
>
> Nenhuma métrica foi produzida e nenhum parecer jurídico foi emitido (ver
> `docs/08` §12). Os gates **G4** e **G6** não foram atingidos. Os artefatos
> locais de modelo são GGUF; o caminho alvo exige safetensors.

## 9. Ordem de execução e paralelismo

**Caminho crítico:**

```text
FND-01 → FND-02 → FND-03 → ING-01 → ING-02 → ING-05
→ IDX-01 → IDX-04 → RET-03 → RET-05 → RET-06 → RET-07
→ GEN-01 → GEN-02 → GEN-05 → EVA-02 → EVA-03 → OPS-01
```

**Trilhas paralelas:**

- **A (dados):** ING-01 → ING-02/03 → ING-04 → ING-05 → ING-06.
- **B (índice alvo):** IDX-02 → IDX-03 → IDX-05 (pode rodar depois do fallback).
- **C (segurança/UI):** GEN-03 → GEN-04 → GEN-05, em paralelo à recuperação.
- **D (avaliação):** EVA-01 pode começar depois de ING-05; EVA-02 depois de RET-07/GEN-05.
- **E (operação):** OPS-01/02 em paralelo; OPS-03 no fim.

O caminho de fallback não depende de GPU. O caminho alvo (9B/Qdrant) é uma trilha separada e só bloqueia o gate G5.

## 10. Gates de qualidade

| Gate | Critério                                   | Bloqueia         |
| ---- | ------------------------------------------ | ---------------- |
| G0   | Plano aprovado e docs 01–10 consistentes   | Início do código |
| G1   | Migração + ingestão P0 + validação         | Índice           |
| G2   | Fallback recupera top-10 nas 20 semeadas   | Geração          |
| G3   | Verificador + emergência 100% nos fixtures | UI pública       |
| G4   | Eval 20 + revisão humana                   | Demo             |
| G5   | Smoke 9B/0.6B top-1 (se GPU)               | Caminho alvo     |
| G6   | 150 perguntas + parecer jurídico           | Publicação       |
| G7   | Backup/restore + LGPD + runbook            | Produção         |

Gates ainda abertos em 2026-11-05:

- [ ] G4 — Eval 20 + revisão humana
- [ ] G5 — Smoke 9B/0.6B (sem GPU/safetensors validados)
- [ ] G6 — 150 perguntas + parecer jurídico

> G1 e G2 dependem de execução com Postgres/Qdrant e não foram verificados
> neste ambiente. G3 tem cobertura unitária de verificador e emergência, mas
> não foi reexecutado em integração. G4, G5 e G6 permanecem **não atingidos**.

## 11. Riscos e mitigação

| Risco                                    | Impacto | Mitigação                                                |
| ---------------------------------------- | ------- | -------------------------------------------------------- |
| Parser do Planalto quebrar               | Alto    | Fixtures + validação de contagem + revisão por amostra   |
| Modelo 9B não couber na GPU              | Médio   | Fallback já pronto; smoke test separado                  |
| LLM escolher versão errada               | Alto    | Versão anexada pela recuperação; teste de data           |
| Citação inexistente virar artigo vizinho | Alto    | Abstenção explícita; teste dedicado                      |
| Dispositivo > max_length                 | Alto    | Split/falha; teste de dispositivo longo                  |
| Hidratação com versões diferentes        | Alto    | Pares `(device_id, norm_version_id)`; teste com 2 normas |
| PII em log/prompt                        | Alto    | Redaction + testes + revisão LGPD                        |
| Jusbrasil sem licença                    | Médio   | Doutrina fora do MVP                                     |
| Base desatualizada                       | Alto    | Job de diff + regressões legais                          |
| Subagentes falhando no runtime           | Médio   | Execução nativa até corrigir OpenCode 1.18.29            |

## 12. Definition of done

- [ ] `docker compose up -d db` sobe o fallback; `docker compose up -d` sobe o alvo.
- [ ] `migrations/001_init.sql` aplica em banco vazio.
- [ ] Ingestão P0 idempotente e validada.
- [ ] Índice fallback funcional; índice alvo com smoke test.
- [x] Citação explícita, hidratação por pares e verificação por versão funcionando
      (evidência unitária; sem execução integrada).
- [x] Emergência e abstenção com testes.
- [ ] 20 perguntas semeadas com métricas; 150 no ciclo seguinte.
- [x] API e UI com aviso legal e fontes (evidência unitária; sem Postgres/Qdrant).
- [ ] CI verde; logs sem PII; backup/restore testado.
- [ ] Revisão jurídica registrada antes de qualquer usuária real.

> As caixas marcadas acima têm evidência unitária, não execução ponta a ponta.
> Docker, migração em banco vazio, ingestão real, índice real, métricas, CI
> observado e revisão jurídica continuam **pendentes**.

## 13. Decisões abertas (não bloqueiam o código)

| Decisão                         | Padrão para desenvolver                 | Quando fechar   |
| ------------------------------- | --------------------------------------- | --------------- |
| LLM local vs API                | mock nos testes; local na demo          | Antes da demo   |
| GPU disponível                  | fallback por padrão; alvo atrás de flag | Antes do G5     |
| Versão exata do `qdrant-client` | lock após smoke test                    | FND-02/IDX-03   |
| Serviços locais                 | 1 município curado                      | Antes do GEN-05 |
| Doutrina                        | fora do MVP                             | Após licença    |
| Revisão jurídica                | pendente                                | Antes do G6     |

## 14. Próximo passo

O plano está consolidado. A execução recomendada neste runtime é **nativa** (uma task por vez, com teste), porque a delegação de subagentes está retornando vazio. Se o runtime for corrigido para OpenCode 1.18.29, a execução pode ser subagent-driven.

**Estado em 2026-11-05 (OPS-03):** o runbook/README foi entregue, mas o
protótipo **não está liberado para demo nem publicação**. Os próximos passos
reais são: ligar os middlewares em `create_app`; expor parsing/carga como CLI;
obter safetensors e executar o smoke 9B/0.6B; implementar
`build_eval_pipeline` e rodar as 150 perguntas com Postgres/Qdrant; e registrar
a revisão jurídica humana. Sem isso, G4 e G6 continuam **não atingidos**.
