# Goldfish Annotated Review Report

**Target:** `docs/05-embeddings-e-recuperacao.md` (`full file; revisão original: 409 linhas`)
**Status:** resolved (round 1); round 2 halted (delegation unavailable)
**Resolution:** 17 PROPOSE FIX endereçados em `02`, `04`, `05`, `06` e `09`; 0 CONTEST, 0 ESCALATE, 0 DECLINE.
**Round:** 1 concluído; rodada 2 não executada.

## Round 2 status

| Reviewer                   | Status  | Notes                                     |
| -------------------------- | ------- | ----------------------------------------- |
| `design_critic`            | not run | Empty result twice.                       |
| `structural`               | not run | Empty result twice.                       |
| `implementation_readiness` | not run | Empty result twice; it worked in round 1. |

Round 2 produced no findings because native reviewer delegation returned empty for all three agents. The OpenCode adapter targets **1.18.29**; this runtime is **2.2.0**. Per the adapter, reviewers are not simulated in the parent context. The loop is halted pending a supported runtime or manual review.

## Round 1 reviewer status

| Reviewer                   | Status    | Notes                                                                           |
| -------------------------- | --------- | ------------------------------------------------------------------------------- |
| `implementation_readiness` | completed | Report received and consolidated below.                                         |
| `design_critic`            | not run   | Returned an empty result twice (initial + retry). Not counted as zero findings. |
| `structural`               | not run   | Returned an empty result twice (initial + retry). Not counted as zero findings. |

Because two reviewers are `not run`, this round is **not clean**. The findings below are only the ones actually raised by `implementation_readiness`.

## Prioritized Findings & AI Suggestions

### 1. [Qdrant contract is not pinned] [`implementation_readiness`] - Severity: Blocker

- **Affected Scope:** [05:79-80, 274-285](docs/05-embeddings-e-recuperacao.md#L79-L80); [02:149](docs/02-arquitetura-e-stack-local.md#L149)
- **Discrepancy Description:** The target path requires a Qdrant collection with multivector `late`, `max_sim`, sparse BM25, and payload filters, but the document defers the API: “A API exata muda entre versões do Qdrant. Verifique a documentação de multivector da versão instalada antes de codificar.” It never pins the server/client version, collection-creation payload, vector names/dimensions/datatype, sparse configuration, payload indexes, or query shape. `02` uses `qdrant/qdrant:latest`, which is nondeterministic.
- **Rationale:** An implementer cannot build or test the target path without inventing the Qdrant contract. The Zero-Decision Rule is violated at the central retrieval component.
- **AI Suggestion:** PROPOSE FIX
- **Justification:** The gap is real and central. The fix is to pin a tested Qdrant version and add a minimal, explicit contract for collection, payload, and query.
- **Proposed Edit:**
  - Location: `05`, insert a new subsection “Contrato Qdrant” after the target architecture requirements (after line 80).
  - Change: Add:
    - Server image pinned in `02` (replace `qdrant/qdrant:latest` with a fixed version, e.g. `qdrant/qdrant:v1.15.3`, the baseline that supports server-side BM25; bump only after the integration test passes).
    - Client pinned in `pyproject.toml` (`qdrant-client==<tested version>`).
    - Collection `devices`:
      - `late`: size `128`, distance `Cosine`, `multivector_config: { comparator: max_sim }`, `datatype: float16`.
      - `bm25`: sparse vector, `modifier: idf`, name `bm25`.
      - Payload indexes: `norm_id`, `artigo_id`, `tipo`, `vigencia_status`, `vigencia_inicio`, `vigencia_fim`, `norm_version_id`.
    - Query shape: prefetch `bm25` top 50, optional dense top 50; fuse by RRF; rescore with `late` (MaxSim); limit 10; `with_payload=true`.
    - State explicitly that the exact Python client call is covered by the integration test, not left to the implementer.

### 2. [Qdrant point identity and versioned-device contract are undefined] [`implementation_readiness`] - Severity: Blocker

- **Affected Scope:** [05:135-137, 142, 165, 180, 239-250, 329-331](docs/05-embeddings-e-recuperacao.md#L135-L137); [04:91, 135, 229, 255-256](docs/04-chunking-e-modelo-de-dados.md#L91)
- **Discrepancy Description:** `device_id` is a slash-delimited string (`lmp/art22/...`), not a native Qdrant point ID (uint64/UUID), and no mapping is defined. The payload omits `norm_version_id` and exact date fields. If one point per device is upserted, the historical filter cannot return old text; if all versions are indexed, point IDs must be version-specific. `04` is also inconsistent: `devices.id` is the primary key, but the document says to create a new version for the same device.
- **Rationale:** Versioned retrieval is a core requirement; without a point identity and version contract, the target cannot answer “qual era a lei na data do fato?”.
- **AI Suggestion:** PROPOSE FIX
- **Justification:** The finding is valid and structural. The fix requires a small schema change, not a rewrite.
- **Proposed Edit:**
  - Location: `04` schema and `05` indexing/retrieval sections.
  - Change:
    - Add `device_versions` (or change `devices` PK to `(id, norm_version_id)`), with `texto_literal`, `contexto`, `citacao`, `vigencia_inicio`, `vigencia_fim`, `redacao_dada_por`, `content_hash`.
    - Add `qdrant_point_id uuid` computed as `UUIDv5(namespace, f"{device_id}@{norm_version_id}")`.
    - Qdrant payload: `device_id`, `norm_version_id`, `artigo_id`, `norm_id`, `tipo`, `vigencia_status`, `vigencia_inicio`, `vigencia_fim`.
    - Keep all versions indexed; default query filters the current version or the version valid at `data_fato`.
    - Change `versao_em(norm_id, data)` to return `norm_version_id`; change `obter_dispositivo` to accept `device_id` + `norm_version_id` (or `data_fato`).
    - Add a hydration query joining Qdrant IDs to Postgres by `(device_id, norm_version_id)`.

### 3. [Target “hybrid” is not fully produced by the target index] [`implementation_readiness`] - Severity: Blocker

- **Affected Scope:** [05:63-65, 129-143, 178, 279, 401](docs/05-embeddings-e-recuperacao.md#L63-L65); [09:24](docs/09-roadmap-prototipo.md#L24)
- **Discrepancy Description:** The target indexing pipeline creates a multivector, payload, `search_text`, and a lexical index, but never a dense vector. Query steps then prefetch “denso (opcional)” without naming its model, dimension, normalization, or index step. If dense is omitted, `09:24` (“denso + lexical”) and the checklist at `05:401` are false. The sparse side is also unspecified: source text, BM25 encoder, IDF handling, vector name, and whether Qdrant computes BM25.
- **Rationale:** The target architecture is described as hybrid, but the actual target index is multivector + sparse. The document must choose one definition.
- **AI Suggestion:** PROPOSE FIX
- **Justification:** The clean fix is to make the target explicitly `late` multivector + `bm25` sparse, and keep dense only in the fallback. That matches the agreed 9B index / 0.6B query design.
- **Proposed Edit:**
  - Location: `05` target architecture and pipelines; `09:24`; `05:401`.
  - Change:
    - Target: `Busca híbrida = multivector late (MaxSim) + BM25 esparso`; remove “denso (opcional)” from target lines 178 and 279.
    - `09:24`: “Busca híbrida (multivector + BM25 esparso) no alvo; denso + FTS no fallback.”
    - `05:401`: replace “A busca densa sozinha...” with “O BM25 esparso sozinho já traz citações explícitas?”
    - Sparse source: `search_text` built from `contexto + texto_literal + citacao`, normalized.
    - Sparse encoder: Qdrant server-side `Qdrant/bm25` (or FastEmbed BM25), `modifier: idf`, vector name `bm25`.
    - State that `search_text` is uploaded to Qdrant or computed there; do not leave it only in Postgres.

### 4. [Pipeline order, fan-out, and candidate caps are undefined] [`implementation_readiness`] - Severity: Major

- **Affected Scope:** [05:177-182, 240-248, 265, 274-285](docs/05-embeddings-e-recuperacao.md#L177-L182)
- **Discrepancy Description:** The order — prefetch top 50 per modality, RRF, filter vigência, dedupe by article, then MaxSim rescore — is not implementable as a single Qdrant request as written. Filtering after fusion can leave fewer than 8–10 candidates. There is no rule for unioning three subqueries, global vs per-subquery dedupe, candidate caps, tie-breaking, or which query text is used for MaxSim.
- **Rationale:** Without exact counts and layer ownership, two implementers will build different retrieval behavior and cannot compare results.
- **AI Suggestion:** PROPOSE FIX
- **Justification:** Valid and fixable with a short, explicit sequence.
- **Proposed Edit:**
  - Location: `05` section 6, target pipeline.
  - Change:
    1. For each subquestion: prefetch `bm25` top 50 and `late` top 50 (or dense top 50 only if explicitly enabled), with the vigência filter applied inside each prefetch.
    2. Fuse by RRF in Qdrant (`FusionQuery`) or Python; state which.
    3. Union across subquestions (max 150); dedupe globally by `artigo_id`, keeping the best RRF score.
    4. MaxSim rescore the 150 with the 0.6B; keep the best leaf per article by MaxSim.
    5. Select 10; if fewer than 10 after filtering, widen to 100 per modality; if still empty, abstain.
    6. Tie-break: higher MaxSim, then newer `vigencia_inicio`, then source priority.
    7. Define whether MaxSim uses the original question (global) or each subquestion (local); use the original for the final rescore.

### 5. [Model loading and encoding are not actionable] [`implementation_readiness`] - Severity: Major

- **Affected Scope:** [05:78, 120, 133-134, 150-151, 291-301, 309](docs/05-embeddings-e-recuperacao.md#L78)
- **Discrepancy Description:** There is no `torch_dtype`, `device_map`, quantization, batch size, `max_length`/truncation policy, output dtype, L2 normalization, or model coexistence plan for 9B + 0.6B. 24 GB is “borderline” with no decision. The storage estimate assumes FP16 but no `datatype` is specified. The fallback code hardcodes `device="cuda"`, contains `[texto_do_dispositivo for ...]`, and gives no exact `MultiVectorEncoder` usage. The pplx context window is “—”, and only Qdrant’s 8,192-token limit is stated.
- **Rationale:** The implementer cannot run the index or reproduce memory behavior without these values.
- **AI Suggestion:** PROPOSE FIX
- **Justification:** Valid; the fix is a configuration block plus exact wrappers.
- **Proposed Edit:**
  - Location: `05`, insert “Configuração de execução” after section 4.
  - Change: Add a table with:
    - `PPX_INDEX_MODEL=perplexity-ai/pplx-embed-v2-late-9b`, `revision=<pinned commit>`, `dtype=bfloat16`, `device=cuda`, `batch_size=1`, `max_length=8192`, `truncation=true`.
    - `PPX_QUERY_MODEL=...0.6b`, `dtype=float16`, `device=cuda`, `batch_size=8`, `max_length=512`.
    - `HARRIER_MODEL=microsoft/harrier-oss-v1-0.6b`, `dtype=float16`, `device=cuda`, `batch_size=32`, `max_length=8192`.
    - `OOM_POLICY`: retry batch 1; then quantize; then fallback.
    - Exact imports and wrappers for `MultiVectorEncoder.encode_document` / `encode_query`; Harrier `model.encode([instruction + query])`.
    - Replace `[texto_do_dispositivo for ...]` with a `textos` list.
    - State that literal text is never truncated before the penalty/inciso tail; truncate context first.

### 6. [Version/reproducibility metadata cannot be persisted] [`implementation_readiness`] - Severity: Major

- **Affected Scope:** [05:142, 165, 389, 408](docs/05-embeddings-e-recuperacao.md#L142); [04:255-256](docs/04-chunking-e-modelo-de-dados.md#L255)
- **Discrepancy Description:** The document requires updating `embedding_model`/`embedding_model_version`, but `04` has only `embedding_model`. Target vectors live in Qdrant, so model, revision, hash, and collection are not stored. “hash do texto” has no algorithm or input definition. HF model IDs are not pinned to revisions. Reindex-on-model-change has no collection/alias procedure.
- **Rationale:** Without persisted metadata, you cannot reproduce, audit, or safely reindex.
- **AI Suggestion:** PROPOSE FIX
- **Justification:** Valid and cheap to fix.
- **Proposed Edit:**
  - Location: `04` schema and `05` index section.
  - Change: Add `embedding_model`, `embedding_model_revision`, `embedding_text_hash`, `indexed_at`, `qdrant_collection` to the device/version table or payload. Define `embedding_text_hash = SHA-256(UTF-8(contexto + "\n" + texto_literal))`. Pin HF `revision` commits. Reindex into `devices_v2`, validate, then alias swap.

### 7. [No component test plan] [`implementation_readiness`] - Severity: Major

- **Affected Scope:** [05:369-375, 395-409](docs/05-embeddings-e-recuperacao.md#L369-L375)
- **Discrepancy Description:** Section 12 is a configuration/tuning checklist, not test cases with inputs and expected outputs. Section 10 lists metrics but no assertions. Missing: RRF known lists, normalization fixtures, vigência boundary dates, dedupe/expansion, MaxSim ordering, fallback parity, empty candidate sets, and the 9B/0.6B shared-space smoke test.
- **Rationale:** The target path cannot be accepted without executable checks.
- **AI Suggestion:** PROPOSE FIX
- **Justification:** Valid; the test plan is a prerequisite for implementation.
- **Proposed Edit:**
  - Location: `05`, new section 13 “Testes de componentes”.
  - Change: Add a table of fixtures and assertions for each item above. Make the shared-space smoke test a gate: index one device with 9B, query with 0.6B, assert top-1.

### 8. [Query understanding has no contract] [`implementation_readiness`] - Severity: Major

- **Affected Scope:** [05:172-176, 192, 250, 337](docs/05-embeddings-e-recuperacao.md#L172-L176); [06:74, 217, 332](docs/06-geracao-citacoes-e-seguranca.md#L74)
- **Discrepancy Description:** “Extrair fatos” lists four concepts but no field names, enums, date normalization, required/optional status, or missing-value behavior. “Reescrever” and “dividir em até 3 subperguntas” have no prompt, model, JSON schema, or parse-failure fallback. `06:74` passes `{json_fatos}` without defining it. Date policy is contradictory: `05:250` says use the current version and ask/signal; `06:217` says abstain when the date is indispensable; `06:332` says explain or ask.
- **Rationale:** The agent cannot reliably produce or consume facts without a schema.
- **AI Suggestion:** PROPOSE FIX
- **Justification:** Valid; a schema and a date decision table resolve the ambiguity.
- **Proposed Edit:**
  - Location: `05`, insert “Contrato de entendimento da consulta” after section 6.
  - Change: Add a JSON schema with `relacao`, `tipo_violencia[]`, `urgencia`, `data_fato` (`YYYY-MM-DD|null`), `uf`, `subperguntas[]`, `consulta_juridica`; define enums and missing semantics. Add prompt version and a fallback to the raw question if parsing fails. Add a date table: (a) deadline/version question + no date → ask once; (b) user declines → answer with “considerando a lei vigente hoje”; (c) old fact with legal change → require date or abstain. Align `05`, `06:217`, `06:332`.

### 9. [Fallback retrieval has no exact SQL or operators] [`implementation_readiness`] - Severity: Major

- **Affected Scope:** [05:189-203, 237-248, 291-301](docs/05-embeddings-e-recuperacao.md#L189-L203); [04:306-322](docs/04-chunking-e-modelo-de-dados.md#L306-L322)
- **Discrepancy Description:** The fallback says “busca densa no pgvector (top 50)” and “FTS (top 50)” but does not specify `ORDER BY embedding <=> :q LIMIT 50`, the FTS function (`websearch_to_tsquery` vs `plainto_tsquery`), language config, `ts_rank_cd`, `@@`, filter placement, or how to combine `search_text` with `search_vector`. The fallback query encoder is unspecified.
- **Rationale:** A wrong operator bypasses the HNSW index; different FTS functions return different rankings.
- **AI Suggestion:** PROPOSE FIX
- **Justification:** Valid; exact SQL is short and removes ambiguity.
- **Proposed Edit:**
  - Location: `05` fallback pipeline.
  - Change: Add exact SQL for dense (`ORDER BY embedding <=> :q LIMIT 50`), FTS (`websearch_to_tsquery('portuguese', :q)`, `ts_rank_cd`, `@@`), and the vigência filter. Specify that dense uses the Harrier query with instruction; lexical uses normalized `search_text`; both use the subquestion, with the original question used for explicit citations.

### 10. [Explicit-citation path is missing] [`implementation_readiness`] - Severity: Major

- **Affected Scope:** [05:171-185](docs/05-embeddings-e-recuperacao.md#L171-L185); [02:220-221](docs/02-arquitetura-e-stack-local.md#L220-L221); [01:86](docs/01-visao-e-escopo.md#L86)
- **Discrepancy Description:** `02` includes “citação explícita → busca direta por ID → contexto” and `01` RF10 requires “buscar por artigo explícito”, but `05` always normalizes, extracts, rewrites, splits, and hybrid-searches. There is no citation parser, ID resolution, ambiguity/nonexistent handling, or precedence rule.
- **Rationale:** The highest-precision path for “art. 24-A” is missing, and a product requirement is unimplemented.
- **AI Suggestion:** PROPOSE FIX
- **Justification:** Valid and directly required by RF10.
- **Proposed Edit:**
  - Location: `05` section 6, before step 1.
  - Change: Add step 0: detect explicit citations with a defined regex/grammar; resolve to `device_id`/`norm_version_id`; fetch directly; if ambiguous or not found, fall back to hybrid or abstain. Define precedence and tests for `art. 7º`, `art. 24-A`, `inciso III`, `alínea b`, nonexistent articles.

### 11. [Context hydration and explanation storage are undefined] [`implementation_readiness`] - Severity: Major

- **Affected Scope:** [05:183-184, 265-268, 313-320](docs/05-embeddings-e-recuperacao.md#L183-L184); [06:81-98](docs/06-geracao-citacoes-e-seguranca.md#L81-L98); [04:190](docs/04-chunking-e-modelo-de-dados.md#L190)
- **Discrepancy Description:** Qdrant payload has metadata and vigência only, so text and citation must be hydrated from Postgres, but no hydration step/query is defined. “explicação” is required in context, but `04` only indexes explanation as a named vector; no text column/table or query-time generation budget is defined. Context budget is only “8–10 devices”; no token/character limit or truncation order.
- **Rationale:** The context cannot be assembled from the specified stores as written.
- **AI Suggestion:** PROPOSE FIX
- **Justification:** Valid; the fix is a hydration query plus a text column/budget.
- **Proposed Edit:**
  - Location: `04` schema and `05` context section.
  - Change: Add `device_explanations(device_id, norm_version_id, texto, gerado_por, revisado)` or a text column. Add hydration SQL joining Qdrant IDs to Postgres by `(device_id, norm_version_id)`. Set total context budget (e.g., 6,000 tokens), per-device literal never truncated, explanation max 200 tokens, doutrina cut first. Mark doc2query named vectors as post-MVP or add them to the collection contract.

### 12. [Latency budget does not match the fan-out] [`implementation_readiness`] - Severity: Major

- **Affected Scope:** [05:176-182, 344-355](docs/05-embeddings-e-recuperacao.md#L344-L355)
- **Discrepancy Description:** The budget states “busca híbrida 100–300 ms” and “rerank 200–800 ms” as stage totals, but the pipeline loops over up to three subquestions, each with dense and sparse top 50, then dedupes and rescores up to ~300 candidates. Subquery concurrency, candidate caps, and fallback CPU budget are unspecified.
- **Rationale:** The p95 target cannot be implemented or verified as written.
- **AI Suggestion:** PROPOSE FIX
- **Justification:** Valid; exact budgets and caps are needed.
- **Proposed Edit:**
  - Location: `05` section 9.
  - Change: State subqueries run in parallel (max 3); per-subquery prefetch 50+50, RRF 50; union max 150; MaxSim 150; final 10. Add target/fallback-specific budgets: target retrieval 600–1,200 ms, rerank 300–600 ms; fallback CPU rerank 1–2 s. Measure p50/p95 on the eval set with hardware specified.

### 13. [Dedupe/expansion order is contradictory] [`implementation_readiness`] - Severity: Major

- **Affected Scope:** [05:180-181, 199, 265-268](docs/05-embeddings-e-recuperacao.md#L180-L181)
- **Discrepancy Description:** The target dedupes by article before rescore and never expands to the full article; the fallback expands; section 6 says globally “Subir para o artigo inteiro”. “Manter o melhor dispositivo-folha” does not define “melhor” (RRF vs MaxSim). Deduping before MaxSim prevents the reranker from choosing a different leaf of the same article.
- **Rationale:** Different orders produce different top-10 sets and different citations.
- **AI Suggestion:** PROPOSE FIX
- **Justification:** Valid; one sequence should be normative.
- **Proposed Edit:**
  - Location: `05` target and fallback pipelines, and section 6 dedupe/expansion.
  - Change: Retrieve leaves → MaxSim rerank leaves → dedupe globally by `artigo_id` keeping the best MaxSim → expand winners to the full article for context. Apply the same sequence to target and fallback (using RRF when MaxSim is absent). State how many leaves per article are kept (one).

### 14. [BM25 normalization grammar is incomplete] [`implementation_readiness`] - Severity: Major

- **Affected Scope:** [05:205-219](docs/05-embeddings-e-recuperacao.md#L205-L219)
- **Discrepancy Description:** The table only has singular examples. It lacks `arts. 5º e 6º`, `§§ 1º a 3º`, `incisos I e II`, `alíneas a e b`, ranges, and quoted alíneas. BM25 is “obrigatório” for explicit citations, so the implementer must invent regex/tokenizer behavior.
- **Rationale:** Recall for explicit citations will vary by implementer.
- **AI Suggestion:** PROPOSE FIX
- **Justification:** Valid; a small grammar and fixture table fixes it.
- **Proposed Edit:**
  - Location: `05` normalization subsection.
  - Change: Add rules and fixtures for plural/ranges/combined citations; state that one normalization function is shared by index and query; use `unaccent` + `portuguese` tokenizer; preserve hyphens in `24-A`.

### 15. [MVP scope is ambiguous] [`implementation_readiness`] - Severity: Nit

- **Affected Scope:** [05:52-54, 82-100, 200, 310, 361-367](docs/05-embeddings-e-recuperacao.md#L52-L54); [09:68-91](docs/09-roadmap-prototipo.md#L68-L91)
- **Discrepancy Description:** The document does not state whether the MVP must implement target, fallback, or both. Rerank is “recommended”, “opcional”, and replaceable/skippable. Section 8’s agent loop and `expandir_remissoes` are presented as design, but `01` and `09` put the graph and multi-tool loop out of MVP.
- **Rationale:** The implementer must choose scope and defaults.
- **AI Suggestion:** PROPOSE FIX
- **Justification:** Valid; a scope table is cheap and prevents overbuilding.
- **Proposed Edit:**
  - Location: `05`, after the title.
  - Change: Add “Escopo desta versão”: target path mandatory when GPU is available; fallback is contingency; agent loop and graph expansion are post-MVP; rerank default per path.

### 16. [No implementation map or phase gates] [`implementation_readiness`] - Severity: Nit

- **Affected Scope:** [05:125-165, 167-203, 270-311](docs/05-embeddings-e-recuperacao.md#L125-L165); [02:184-208](docs/02-arquitetura-e-stack-local.md#L184-L208); [09:68-91](docs/09-roadmap-prototipo.md#L68-L91)
- **Discrepancy Description:** `05` gives pipelines but no files/functions or phase gates. `02` suggests module paths and `09` gives phases, but `05` does not reference them as normative.
- **Rationale:** A fresh implementer must infer boundaries and may touch adjacent code.
- **AI Suggestion:** PROPOSE FIX
- **Justification:** Valid; a short cross-reference fixes it.
- **Proposed Edit:**
  - Location: `05`, end of document.
  - Change: Add “Mapa de implementação”: `src/index/embed.py`, `src/retrieve/hybrid.py`, `src/retrieve/rerank.py`, `src/retrieve/expand.py`; state that `02 §5` and `09 §3` are normative for file boundaries and phase acceptance.

### 17. [Consistency cleanups] [`implementation_readiness`] - Severity: Nit

- **Affected Scope:** [05:13, 21-25, 64, 85, 133, 183, 201, 294, 336, 363](docs/05-embeddings-e-recuperacao.md#L13)
- **Discrepancy Description:** Requirement `05:13` says “Mesmo modelo para indexar e consultar”, while the target uses 9B/0.6B and `05:382` says “mesmo modelo ou família”. Model IDs vary in casing (`harrier-oss-v1-0.6b` vs `0.6B`, `pplx...-9b` vs `9B`); ranges 8–10 devices and 2–3 loop iterations remain open.
- **Rationale:** Copy/paste and configuration ambiguity.
- **AI Suggestion:** PROPOSE FIX
- **Justification:** Valid and low-cost.
- **Proposed Edit:**
  - Location: `05`.
  - Change: Add a constants table with canonical HF IDs; change requirement 05:13 to “mesmo espaço vetorial/família”; fix defaults to 10 devices and 3 loop iterations (or make them named config values).

## Summary

**3 Blockers, 11 Majors, 3 Nits.** The document is a strong architecture decision record, but it is not implementation-ready under the Zero-Decision Rule. The blockers all concern the target Qdrant path: pinned contract, point identity/versioning, and the target hybrid definition. Two of the three reviewers (`design_critic`, `structural`) did not run because they returned empty results twice; the round is therefore not clean and should not be treated as converged.
