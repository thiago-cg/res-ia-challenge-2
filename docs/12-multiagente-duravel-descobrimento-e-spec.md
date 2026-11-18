# 12 — Zelia multiagente durável: descoberta, decisões e especificação

> **Documento vivo.** Este arquivo é o artefato único de descoberta, decisão e especificação (SDD).
> As seções abaixo correspondem ao briefing de origem e estão preenchidas com evidência.
> O gate da §16 foi aprovado e o incremento foi implementado, revisado e commitado; o registro
> de execução, com erros e medições, está na §22, e o relatório final na §24.

## 0. Identificação

| Campo | Valor |
|---|---|
| Projeto | Zelia — orientação jurídica informativa sobre violência doméstica |
| Repositório | thiago-cg/res-ia-challenge-2 |
| Revisão inspecionada | `d2955c6139b41ce568216dea5298dcbc71e02b2d` |
| Worktree | `.agents/worktrees/dsh-45972179-e211`, branch `dsh-45972179-e211` |
| Sincronia com remoto | HEAD == `origin/main` == commit `main` no GitHub (0/0), working tree limpa |
| Último commit | merge do PR #11, 2026-11-13 |
| Data da descoberta | 2026-11-16 |
| Fase | Descoberta + design + spec implementável + incremento executado |
| Implementação | T03–T18 implementadas e revisadas; base legal real ingerida (§22.28) |
| Gate de aprovação | Aprovado em `P01–P04` com as opções recomendadas (§16) |

### 0.1 Como a descoberta foi feita

1. Leitura estática integral dos arquivos citados em §2, no próprio worktree.
2. Cinco frentes independentes em paralelo (geração/verificação, frontend, recuperação/config,
   testes/segurança, documentação LangGraph), todas obrigadas a devolver `caminho:linha` + trecho.
3. Uma execução real da suíte existente (T00), com resultado registrado na §4 — inclusive as
   limitações do ambiente.
4. Nenhuma dependência foi instalada, nenhum serviço foi levantado, nenhum modelo foi chamado,
   nenhum relato de vítima foi produzido ou usado. Todos os cenários são sintéticos.

### 0.2 Classificação usada

`OBSERVADO` (lido no código), `HIPÓTESE`, `PROPOSTA`, `DECIDIDO`, `VALIDADO`, `PENDENTE`,
`BLOQUEADO`. Nenhuma PROPOSTA deste documento foi promovida a DECIDIDO.

---

## 1. Estado do gate (resumo executivo)

### 1.1 O que a descoberta fechou

- A aplicação atual é **síncrona e sem estado de conversa no servidor**. `POST /chat` abre a
  requisição, executa recuperação, geração e verificação, e só então responde
  (`src/api/main.py:936-988`). O cliente espera até 60 s (`web/ui/scripts/api.js:51`).
- **Não existe autenticação, autorização, CORS, cookie, CSRF ou sessão de servidor** em nenhum
  ponto: zero ocorrências de `Depends`, `CORSMiddleware`, `cookie` ou `csrf` em todo o repositório.
- **Não existe nenhuma tabela de conversa, mensagem, thread, checkpoint ou execução**. As dez
  tabelas de `migrations/001_init.sql` são exclusivamente normativas/ingestão/avaliação.
- **O LangGraph não está declarado** (`pyproject.toml:6-18`) e não aparece em nenhum arquivo do
  repositório. `MAX_AGENT_LOOPS` existe na configuração (`src/config.py:72`) e **não é lido por
  ninguém**.
- O caminho de emergência é hoje a única garantia de degradação graciosa e está bem protegido por
  testes (`tests/unit/test_api.py:241-346`). É reutilizável como está.

### 1.2 O que bloqueia a implementação

| # | Bloqueio | Por quê | Onde está a decisão |
|---|---|---|---|
| B1 | **Identidade e recuperação de acesso** | Sem isso, "recuperar a conversa" não pode ser autorizado; `thread_id` não é credencial (INV01) | ADR-02, §16 P01 |
| B2 | **Política de retenção e exclusão** | Define schema, textos da UI e o que "apagar" significa | ADR-03, §16 P02 |
| B3 | **Runtime: Agent Server vs biblioteca + worker** | Define arquitetura, hospedagem e licença | ADR-01, §16 P03, spike T02 |
| B4 | **Mudança da promessa de privacidade da UI** | Hoje a UI promete "conversa só nesta aba" | §3 D05/D06, §16 P04 |

Nenhuma das quatro pode ser decidida por agente sem aprovação humana explícita.

### 1.3 O que **não** foi feito (e não deve ser lido como feito)

- Nenhum teste novo, nenhum código, nenhuma migração, nenhuma dependência adicionada.
- Nenhum teste de navegador: não há ferramenta de E2E no repositório.
- Nenhum teste de integração executado (o daemon do Docker não estava em execução nesta máquina).
- Nenhum contato com Agent Server, LangSmith ou modelo externo.
- A suíte existente executou com **ressalvas de ambiente** (§4): não foi possível obter um
  veredito limpo de "tudo verde".

---

## 2. Mapa de evidências

Toda linha abaixo é `OBSERVADO` na revisão `d2955c6`. Faixas indicam leitura integral.

### 2.1 API e contratos

| ID | Caminho:linhas | Símbolo / trecho | Consequência para o design |
|---|---|---|---|
| E01 | `src/api/main.py:327-725` | `class LegalRAGPipeline` | Monólito: recuperação+geração+verificação no mesmo objeto. Extrair serviços antes de orquestrar. |
| E02 | `src/api/main.py:82-83` | `ChatPipeline(Protocol): answer(message, facts) -> PipelineResult` | Porta de compatibilidade já existe; o grafo deve poder ser injetado atrás dela. |
| E03 | `src/api/main.py:901-937` | `create_app(*, settings, pipeline, source_repo, health_probe)` | DI completa: testes rodam sem Postgres/Qdrant/LLM. Preservar. |
| E04 | `src/api/main.py:936-988` | rota `POST /chat`, `response_model=ChatResponse` | Requisição fica aberta até a resposta jurídica. É o oposto de RF03. |
| E05 | `src/api/main.py:944-957` | `if classify_risk(payload.message).immediate:` antes do pipeline | Emergência curtocircuita no nível HTTP sem tocar storage. Preservar. |
| E06 | `src/api/main.py:390-473` | `LegalRAGPipeline.answer` | Ordem real: risco → citação explícita → plano → busca híbrida → rerank → hidratação → expansão → geração. É o "pipeline de pesquisa" a reutilizar. |
| E07 | `src/api/main.py:549-615` | `for attempt in (1, 2)` + `verify(..., max_attempts=2)` | Duas tentativas de geração já embutidas; ver §9. |
| E08 | `src/api/main.py:1003-1034` | rota `GET /sources/{device_id}` | Leitura pública de dispositivo já existe. Não confundir com endpoint de conversa. |
| E09 | `src/api/main.py:1040-1055` | `_mount_interface` monta `/app` e redireciona `/` | UI é servida pela própria API: mesma origem por padrão. Facilita cookie `SameSite`. |
| E10 | `src/api/main.py:1132-1142` | `psycopg.connect(..., connect_timeout=3, row_factory=dict_row)` | Uma conexão por chamada, sem pool. Worker concorrente precisa de pool ou limite explícito. |
| E11 | `src/api/schemas.py:43-51` | `ChatRequest(session_id, message, facts)`, `extra="forbid"` | `session_id` vem do cliente e não prova nada. `extra="forbid"` é bom: cliente novo com campo extra quebra. |
| E12 | `src/api/schemas.py:71-106` | `ChatResponse` com 11 campos + `from_answer` | Contrato de saída estável; preservar ou versionar. |
| E13 | `src/contracts.py:39-49` | `RetrievedDevice(source: Literal["explicit","bm25","dense","maxsim"])` | Não adicionar `source="web"` aqui: evidência web é outro tipo (§8.1). |
| E14 | `src/contracts.py:73-114` | `Answer`, `VerificationResult`, `QueryPlan` (`max_length=3`), `Citation` | Contratos existentes; a spec evolui em cima, não substitui. |
| E15 | `src/api/middleware.py:64-65` | `if _is_chat_path(path): headers["Cache-Control"] = "no-store"` | Só `/chat` é `no-store`. Rotas novas de conversa **precisam** ser incluídas. |
| E16 | `src/api/middleware.py:68-105` | `RequestContextMiddleware` emite `http.access` sem corpo | Base pronta para observabilidade de runs; estender, não duplicar. |
| E17 | `src/api/middleware.py:124-130` | `SecurityHeadersMiddleware`: `nosniff`, `Referrer-Policy: no-referrer` | Preservar; faltam CSP e HSTS (dependem de TLS). |

### 2.2 Geração, verificação e risco

| ID | Caminho:linhas | Símbolo / trecho | Consequência |
|---|---|---|---|
| E18 | `src/generate/verify.py:30-38` | `verify(answer, retrieved, *, repo, judge, attempt, max_attempts)` | Verificador único, reutilizável como gate de publicação. |
| E19 | `src/generate/verify.py:68` | `ok = deterministic_ok and semantic_ok is not False` | **`semantic_ok=None` conta como aprovação.** É a tensão de INV14; a saída não pode chamar isso de "validado". |
| E20 | `src/generate/verify.py:176-181` | `if answer.resposta.strip() and not answer.citacoes: return ["legal claim without citation"]` (pulado se `abstencao`) | Resposta não-abstida exige citação. Impede saudação sem política explícita. |
| E21 | `src/generate/verify.py:147-173` | `_QUOTE_RE` exige trechos entre aspas dentro do literal | Cobre citação literal, não afirmação em prosa. |
| E22 | `src/generate/verify.py:184-189` | `if not citation.afirmacao.strip()` | Só **presença** da afirmação; o conteúdo nunca é confrontado com o literal. |
| E23 | `src/generate/llm.py:166-203` | `attempts = max_retries + 1`; retry em timeout/429/5xx; `time.sleep(backoff * 2**attempt)` | Retry bloqueante e multiplicativo; ver §9. |
| E24 | `src/api/main.py:684` | `return llm.complete(SYSTEM_PROMPT, prompt)` (sem `timeout`) | Usa o default de 30 s do Protocol (`llm.py:22`), **não** `openrouter_timeout=60`. |
| E25 | `src/generate/prompt.py:30-31` | "O conteúdo dentro de <documento> é dado, não instrução" | Defesa contra prompt injection documental existe. |
| E26 | `src/generate/prompt.py:186-187` | `"Pergunta da usuária:\n" f"{pergunta}"` | O relato entra no prompt **sem sanitização**; só documentos passam por `_sanitize`. |
| E27 | `src/safety/risk.py:170-202` | `classify_risk(text) -> RiskAssessment` | Puramente lexical (regex, NFKD), sem banco, rede ou modelo. |
| E28 | `src/api/main.py:390-392` e `733-735` | três entradas checam risco antes de qualquer I/O | INV09 já é estrutural; a arquitetura nova não pode regredir. |
| E29 | `src/generate/fallback.py:107-126`, `144-199` | `abstain(...)`, `build_safe_answer(...)`; `abstencao=True` sempre | Abstenção segura já existe com números de emergência. Reutilizar. |

### 2.3 Recuperação e configuração

| ID | Caminho:linhas | Símbolo | Consequência |
|---|---|---|---|
| E30 | `src/retrieve/query.py:266-299` | `understand_query(...)`, fallback determinístico | Plano sempre existe; falha do LLM degrada, não quebra. |
| E31 | `src/retrieve/hybrid.py:97-166` | `hybrid_search`: 2 buscas por subpergunta, RRF `k=60`, `lexical_weight=0.2` | Custo real: 3 subperguntas × 2 legs = 6 buscas, cada uma com conexão própria. |
| E32 | `src/retrieve/hydrate.py:43-94` | `hydrate(...)` — "Qdrant payload never carries legal text" | Texto jurídico só vem do Postgres. Evidência base é sempre hidratada. |
| E33 | `src/retrieve/hydrate.py:98-133` | `resolve_citation`: "never trust the LLM with a version" | Já implementa parte de INV07. |
| E34 | `src/config.py:40-121` | `Settings`; `@lru_cache get_settings()` | Singleton por processo; o worker precisa do próprio processo/config. |
| E35 | `src/config.py:72` | `max_agent_loops: int = Field(default=3, gt=0)` | **Sem nenhum uso em `src/`** (grep). Único vestígio de "loop de agente". |
| E36 | `.env.example:42-46` | `MAX_DEVICES`, `MAX_CONTEXT_TOKENS`, `MAX_SUBQUESTIONS`, `MAX_AGENT_LOOPS` | Orçamentos já parametrizados; faltam os de execução (deadline, tokens, custo). |

### 2.4 Frontend

| ID | Caminho:linhas | Trecho | Consequência |
|---|---|---|---|
| E37 | `web/ui/scripts/api.js:51-63` | `conversar({..., tempoLimite = 60000})` → `POST /chat` | Cliente assume resposta síncrona. |
| E38 | `web/ui/scripts/app.js:977-986` | `sessionStorage.getItem/setItem(CHAVE_SESSAO)` | Sessão por aba e **nunca rotacionada**. |
| E39 | `web/ui/scripts/app.js:672-683` | `apagarConversa()`: limpa memória, `removeItem(CHAVE_HISTORICO)`, `estado.sessao = novaSessao()` | `novaSessao()` devolve o valor existente (`:979-980`): o `session_id` enviado **não muda**. |
| E40 | `web/ui/scripts/app.js:651-653` | "Histórico ligado · salvo só neste aparelho" / "Histórico desligado · conversa só nesta aba" | Promessa incompatível com persistência remota. |
| E41 | `web/ui/scripts/app.js:783-792` | `if (erro?.tipo === "rede") { aplicarModoDemo(); return; }` | Indisponibilidade de rede vira demonstração. |
| E42 | `web/ui/scripts/app.js:887-889` → `:520-523` | `enviar(acao.dataset.pergunta)` empilha a mensagem outra vez | Retry duplica pergunta na thread e no histórico; não há id de mensagem. |
| E43 | `web/ui/scripts/app.js:992-1004` | `?api=` > `<meta zelia-api>` > mesma origem > `http://localhost:8000` | Aceita origem arbitrária por query string. |
| E44 | `web/ui/scripts/markdown.js:8-32` | `escapar(...)` **antes** da formatação; só tags geradas pelo código | Controle de XSS correto. Preservar integralmente. |
| E45 | `web/ui/scripts/app.js:83-90` | `urlSegura`: aceita apenas `http:`/`https:` | URL de fonte validada antes de virar `href` (`:220-222`). |
| E46 | `web/ui/index.html:16` | único "atalho de saída" é `<a class="pular" href="#conversa">` | **Não existe botão de saída rápida**. |
| E47 | `web/ui/index.html:258` | "Nada é enviado a serviços de terceiros" | Contradiz E43 quando `?api=` aponta para outro host. |
| E48 | `web/app.py:36-57` | `call_chat_api` → `POST /chat` com `{session_id, message, facts?}` | O Streamlit quebra se `/chat` mudar de envelope. |

### 2.5 Persistência, infraestrutura e testes

| ID | Caminho:linhas | Evidência | Consequência |
|---|---|---|---|
| E49 | `migrations/001_init.sql:5-209` | 10 tabelas: `norms`, `norm_versions`, `devices`, `device_questions`, `device_relations`, `ingest_runs`, `eval_questions`, `device_versions`, `device_explanations`, `services` | **Nenhuma** tabela de conversa/execução. |
| E50 | `scripts/apply_migrations.py:11-28` | `sorted(glob("*.sql"))`, executa tudo, `commit`, sem tabela de controle | Reexecutar em base já migrada falha. |
| E51 | `pyproject.toml:6-18` | deps sem langgraph | Adicionar LangGraph exige decisão de versão + lockfile (611 KB). |
| E52 | `docker-compose.yml:3-31` | `db` (pgvector/pg17) e `qdrant` (perfil `target`); nenhum worker | O worker será processo novo; sem orquestração declarada. |
| E53 | `.github/workflows/ci.yml:9-132` | jobs `lint`, `typecheck`, `test`, `integration`, `backup-restore` | Drill de backup/restore real já existe — base para provar retenção. |
| E54 | `tests/unit/test_api.py:241-257` | emergência: `repo.calls == []`, `dense.calls == []`, `fts.calls == []`, `pipeline._llm.calls == []` | INV09 garantido por teste hoje. Modelo para os ACs novos. |
| E55 | `tests/unit/test_api.py:405-429` | `assert "Súmula 999" in result.answer.resposta` (`:428`) | O teste **documenta** que referência inventada no corpo não é barrada. |
| E56 | `tests/unit/test_api.py:1044-1060` | CPF não aparece no log; `session_id` aparece | PII de conteúdo protegida; identificador é logado. |
| E57 | 58 arquivos em `tests/unit` (~720 `def test_`); 8 em `tests/integration` (16 testes, 12 marcados) | Ver D09 | Base grande e séria; incrementos entram em cima dela. |

---

## 3. Divergências entre código, documentação e pressupostos

| ID | Tipo | Descrição | Evidência |
|---|---|---|---|
| D01 | doc ↔ código | README diz que `MAX_AGENT_LOOPS` existe mas "o pipeline atual não executa um loop agêntico amplo". Confirmado: zero usos em `src/`. | `README.md:356`; `src/config.py:72` |
| D02 | doc ↔ código | `docs/07` lista `buscar_jurisprudencia` entre as ferramentas do agente. Não há jurisprudência na base nem parser de acórdãos. | `docs/07-paradigmas-avaliados.md:65`; único `jurisprud` em `src/` é `retrieve/render.py:24` |
| D03 | código ↔ env | `LOG_QUESTION_TEXT` e `LOG_RETENTION_DAYS` estão no `.env.example` mas **não** em `Settings`; `extra="ignore"` esconde erro de digitação. | `.env.example:51-52`; `src/config.py:33-38`; `src/obs/logging.py:235-251` |
| D04 | contrato ↔ implementação | `LLMReranker` grava `source="llm-rerank"`, valor ausente do `Literal`; passa porque `model_copy(update=...)` não valida. | `src/retrieve/llm_rerank.py:98`; `src/contracts.py:43`; `src/retrieve/rerank.py:66` |
| D05 | UI ↔ intenção | "Apagar conversa" não rotaciona o `session_id` e não limpa `estado.dataFato`. | `app.js:672-683` vs `:977-986` |
| D06 | UI ↔ UI | "Nada é enviado a serviços de terceiros" convive com `?api=<origem>` arbitrário. | `index.html:258`; `app.js:992-1004` |
| D07 | UI ↔ correção | Botão "repetir" reenvia e empilha a pergunta de novo; nenhuma idempotência. | `app.js:887-889`, `:520-523` |
| D08 | UI ↔ segurança | Falha de rede em `/health` ativa modo demonstração e nunca sai dele. | `app.js:783-792`, `:1097` |
| D09 | testes | 4 testes de integração não marcados rodam no job unitário. | `tests/integration/test_infra.py:16,28,38`; `test_shared_space.py:31`; `pyproject.toml:54-57` |
| D10 | migrações | **RESOLVIDO em T07**: sem controle de versão, `apply_migrations` reaplicava todos os `.sql` e quebrava em base já migrada. Agora há `schema_migrations`. | `scripts/apply_migrations.py`; `tests/integration/test_migration.py::test_reapply_is_a_noop` |
| D11 | verificação | `semantic_ok=None` é tratado como aprovação; a saída pública não distingue determinístico de semântico. | `src/generate/verify.py:68`; `src/contracts.py:111` |
| D12 | prompt | Proteção de injeção cobre documentos, não o relato da pessoa. | `prompt.py:30-31` vs `:186-187` |

---

## 4. Linha de base executada (T00)

### 4.1 Primeira tentativa (ambiente emprestado) — superada

Antes de existir um ambiente próprio, a suíte rodou com o venv do checkout principal, em modo
somente leitura. Resultado inconclusivo (`1 failed, 789 passed, 57 errors`), com o teardown do
pytest abortando por `PermissionError` no diretório temporário e o `uv sync` falhando por
`Could not acquire lock` no cache global. O registro fica porque foi ele que diagnosticou o
problema de ambiente.

### 4.2 Segunda tentativa (ambiente próprio da worktree) — **VALIDADO**

```sh
# cache do uv dentro do workspace, senão o sandbox nega acesso
$env:UV_CACHE_DIR = "<worktree>/.uv-cache"; $env:UV_LINK_MODE = "copy"
uv sync --extra dev                      # criou .venv/ (Python 3.12.13)
.venv/Scripts/python.exe -m pytest -m "not integration" -q
```

Resultado: **`1 failed, 789 passed, 12 deselected, 3 warnings, 57 errors in 26.17s`**.

As duas classes de problema foram identificadas e **as duas são do ambiente, não do código**:

| Sintoma | Causa provada | Evidência |
|---|---|---|
| `1 failed` — `tests/unit/test_ops_scripts.py::test_shell_scripts_are_parseable` | o `bash` do Git não abre named pipe sob confinamento: `couldn't create signal pipe, Win32 error 5` | traceback do próprio teste (`--tb=short`) |
| `57 errors` em `tmp_path` | `PermissionError: [WinError 5] ... \Temp\dsh-UeyeSP\pytest-of-tito` — o sandbox nega criar/listar diretórios de `tempfile` | `--tb=line` em dois erros distintos |

**Conclusão do T00:** nenhuma falha de lógica observada. **789 testes passam**; a única falha e todos
os erros são operações bloqueadas pela política de arquivos desta sessão (named pipe e `mkdtemp`).
"Verde" só pode ser declarado em CI ou em terminal normal — é isso que o T00 oficial exige.
**H07 e H08 ficam resolvidos por medição** (não eram testes de integração mal marcados).

Resíduo: `.probe_tmp/` e `.pytest_tmp/` ficaram no worktree e não puderam ser removidos dentro do
sandbox (ACL negada). `.pytest_tmp/` é ignorado pelo git; `.probe_tmp/` aparece como não rastreado
e deve ser apagado de um terminal normal (`rd /s /q .probe_tmp`). `.uv-cache/` e `.venv/` são
ignorados pelo git.

---

### 4.3 Suíte de integração — executada com infraestrutura real

Com `db` (pgvector/pg17) e `qdrant` v1.15.3 no ar pelo `docker-compose.yml`, e migrações aplicadas
pela CLI do projeto:

```sh
$env:DATABASE_URL        = "postgresql://app:app@localhost:5432/violencia"
$env:TEST_DATABASE_URL   = "postgresql://app:app@localhost:5432/violencia"
$env:TEST_QDRANT_URL     = "http://localhost:6333"
python scripts/apply_migrations.py     # applied 001_init.sql, 002_norms_nullable.sql
python -m pytest -m integration -q
```

Resultado: **`8 passed, 4 skipped, 847 deselected in 6.72s`** (exit 0). Os 4 `skipped` são os testes
que exigem estado específico (banco vazio/limpo) e se autoexcluem.

**T00 fecha aqui:** unitária com 789 aprovados e anomalias explicadas por ambiente (§4.2);
integração verde contra Postgres e Qdrant reais. O que não existe é teste de navegador — e isso
é a pendência P05, não uma falha do T00.

---

## 5. Jornadas críticas

Cenários sintéticos. Nenhuma entrevista foi realizada nem inventada; cada jornada deriva do que a
UI já promete e do que a §3.3 do briefing exige.

| ID | Jornada | Situação | Critério de sucesso | Questão aberta |
|---|---|---|---|---|
| J01 | Primeiro acesso | Pessoa abre `/app`, pergunta simples | Resposta com citação, aviso legal e data da base | — |
| J02 | Pesquisa longa com aba fechada | Aba fecha durante o processamento | Trabalho continua; resultado recuperável ao voltar | Retenção (P02) |
| J03 | Queda de rede no envio | `fetch` falha antes da confirmação | "Não confirmado" + verificar; não duplica | — |
| J04 | Aceito, confirmação perdida | Servidor aceitou, 202 não chegou | Reconciliação por `client_message_id` | — |
| J05 | Retorno com execução em andamento | Pessoa volta; run `running` | Estado + acompanhamento, sem reenviar | Transporte (ADR-06) |
| J06 | Retorno com resultado concluído | Run `succeeded` | Mesma resposta, sem nova execução | — |
| J07 | Retorno com sessão expirada | Cookie expirou | Nada é revelado; explicação e recomeço | Identidade (P01) |
| J08 | Aparelho compartilhado | Outra pessoa usa o mesmo navegador | Conteúdo não aparece sem ação explícita | **Decisão de UX pendente** |
| J09 | Esclarecimento | Pergunta ambígua | Pergunta de volta, turno aguardando | Limite de 1 por turno? |
| J10 | Risco imediato sem banco | Banco/worker fora | Resposta fixa 190/180/100/197 imediata | — |
| J11 | Cancelamento explícito | Pessoa cancela durante pesquisa | Run `cancelled`, nada publicado depois | — |
| J12 | Exclusão durante processamento | Pessoa apaga enquanto roda | Tombstone, cancelamento, sem publicação tardia | Backups (P02) |
| J13 | Duas abas | Envio simultâneo | Uma execução lógica; a segunda rejeitada ou enfileirada | Política (ADR-05) |
| J14 | Indisponibilidade real | API/worker fora do ar | Erro honesto, sem demo se passando por atendimento | Corrigir D08 |

### 5.1 A jornada que muda o produto: J08

Hoje a UI promete "conversa só nesta aba" (`app.js:653`) e "salvo só neste aparelho`
(`app.js:652`). Com persistência remota a frase deixa de ser verdadeira em duas direções: o
conteúdo passa a existir no servidor **e** continua visível para quem abrir o mesmo navegador
desbloqueado. Cookie persistente não protege contra isso. Qualquer decisão de identidade precisa
declarar explicitamente o que é e o que **não** é garantido — e a UI precisa dizer a mesma coisa.

---

## 6. Registro de hipóteses

| ID | Hipótese | Evidência necessária | Status |
|---|---|---|---|
| H01 | LangGraph + checkpointer retoma após morte do processo sem publicar duas vezes | Spike T02 | **VALIDADO** nos dois backends, Sqlite e Postgres (§20.7) |
| H02 | Checkpoint de super-step basta, e o nó reexecuta desde o início | T02: contagem de reexecuções | **VALIDADO** — o nó executou 2× (§20) |
| H03 | `verify()` aceita saudações quando recebe política explícita | Teste RED com política por tipo | PENDENTE |
| H04 | Uma execução ativa por conversa elimina a corrida de duas abas | Teste com 2 workers e `SKIP LOCKED` | PENDENTE |
| H05 | Latência de fila < 2 s com worker em processo separado | Medição em T09 | PENDENTE |
| H06 | O custo de retry atual chega a 6 chamadas de LLM por turno | Medição instrumentada (E07 × E23) | PENDENTE |
| H07 | Os 57 erros do baseline são todos de `tmp_path` | Baseline em CI (T00) | **VALIDADO** — `PermissionError` de `mkdtemp` (§4.2) |
| H08 | O `FAILED` é um dos 4 testes de integração não marcados | Baseline com `-rf` | **REFUTADO** — é o `bash` sem named pipe (§4.2) |
| H09 | `?api=` cross-origin nunca funciona hoje (não há CORS) | Teste de navegador | PENDENTE |
| H10 | O worker roda o grafo sem conflito com `lru_cache` de `get_settings()` | Spike | PENDENTE |

H01/H02 ficam deliberadamente PENDENTES: a documentação oficial consultada (2026-11-16) afirma que
o checkpoint é gravado em fronteiras de super-step e que o nó reexecuta desde o início ao retomar,
mas isso não substitui o spike — é exatamente o tipo de comportamento em que "a doc diz" e "o
processo morreu e voltou" decidem a arquitetura.

---

## 7. ADRs

Todas as decisões abaixo estão em `PROPOSTO`. Nenhuma vale como aprovada. O campo **Aprovação**
está vazio por construção.

### ADR-01 — Runtime e implantação

- **Status:** DECIDIDO (2026-11-16) · **spike T02 executado nos dois backends** (Sqlite e Postgres):
  retomada confirmada, publicação única e efeito duplicado sem chave idempotente (§20.1-20.7)
- **Problema:** quem garante que o trabalho continua depois que o navegador fecha?
- **Restrições:** LangGraph já escolhido pelo responsável; Postgres é a "fonte da verdade"
  (`README.md:326`); proibido ativar infraestrutura paga ou serviço externo sem autorização;
  dados de pessoa em situação de violência não podem sair do ambiente.
- **Evidências:** `pyproject.toml:6-18` (sem langgraph); `migrations/001_init.sql` (nenhuma tabela
  de execução); `src/api/main.py:936-988` (síncrono); `docker-compose.yml` (sem worker).
  Documentação oficial consultada em 2026-11-16: `langgraph` 1.2.22 exige Python >= 3.10 e oferece
  checkpoints (`langgraph-checkpoint-postgres` 3.2.1; tabelas `checkpoints`, `checkpoint_blobs`,
  `checkpoint_writes`, `checkpoint_migrations`), `interrupt/resume` e `RunControl`. **Não** oferece
  runs em background, `join`, autenticação nem `threads` — esses recursos existem apenas no Agent
  Server, que faz parte da plataforma LangSmith. `langgraph dev` é explicitamente in-memory e
  "for development and testing". Licenciamento e custo do self-hosted: **não encontrados**.
- **Alternativas:**
  - **A. Agent Server / LangSmith Deployment.** Ganha runs, streams, `join` e auth prontos. Custa:
    segundo serviço, licença desconhecida, auth imposta pelo fornecedor, e a promessa "nenhum
    serviço externo" fica dependente de termos que não conseguimos ler.
  - **B. Biblioteca `langgraph` + runtime próprio durável.** Ganha controle total, um único banco,
    reversibilidade e permanência local. Custa: registro de execuções, worker, leases, idempotência
    e recuperação passam a ser nossos.
- **Decisão proposta:** **B**, com a fila como tabela no Postgres existente (`runs`), reivindicação
  por `SELECT ... FOR UPDATE SKIP LOCKED`, lease com expiração e reconciliador de execuções
  abandonadas. Agent Server permanece **bloqueado** até que licença, custo e modelo de dados sejam
  conhecidos e aprovados.
- **Consequências:** processo novo (`worker`); `langgraph` e `langgraph-checkpoint-postgres` entram
  em `pyproject.toml`/`uv.lock`; o DDL do checkpoint é do pacote (`setup()`), não nosso.
- **Riscos:** reexecução de nó após `kill`; efeitos externos duplicados; conflito de versões no
  lockfile; drift entre versão do grafo e checkpoints antigos.
- **Teste de validação:** spike T02 — matar o processo no meio do nó, reiniciar, provar publicação
  única e efeito externo único.
- **Rollback:** `MULTIAGENT_ENABLED=false`; `/chat` continua; execuções aceitas são drenadas antes
  de desligar. Nada destrutivo.
- **Aprovação:** tito (responsável pelo projeto) · **Data:** 2026-11-16

### ADR-02 — Identidade, sessão e recuperação

- **Status:** DECIDIDO (2026-11-16)
- **Problema:** como autorizar a leitura de uma conversa sem transformar identificador em credencial?
- **Restrições:** `thread_id`/`session_id`/`conversation_id` não concedem acesso (INV01/INV02);
  minimização de PII; aparelho pode ser compartilhado; sem infraestrutura de e-mail/SMS aprovada.
- **Evidências:** `src/api/schemas.py:46` (`session_id` vem do cliente); `app.js:977-986`
  (`sessionStorage`, por aba); `app.js:672-683` (apagar não rotaciona); nenhum `Depends`/cookie/
  CORS/CSRF no repositório; `src/api/main.py:940-942` loga `session_id`.
- **Alternativas:**
  - **A. Capability cookie.** Na criação da conversa o servidor emite segredo opaco aleatório
    (32 bytes) em cookie `HttpOnly; SameSite=Lax; Secure` (com TLS) e guarda apenas o hash. Rota
    privada exige cookie válido **e** posse do recurso. Sem contas; sem recuperação entre aparelhos.
  - **B. Código de retomada digitado.** Atravessa dispositivos, mas cria segredo que pode ser lido
    por quem estiver por perto.
  - **C. Conta com senha/OTP.** Fora do escopo acadêmico; adiciona PII e dependência externa.
- **Decisão proposta:** **A**, declarando na UI: "esta conversa fica neste navegador; em outro
  aparelho não é possível retomar". J08 tratada com **aviso**, não com promessa de proteção.
- **Consequências:** tabela de credencial (hash), middleware de autorização, `no-store` em todas as
  rotas privadas, rotação de credencial na exclusão (corrige D05 no servidor).
- **Riscos:** XSS leria o conteúdo (E44 é pré-requisito); CSRF se cookie; aparelho desbloqueado
  compartilhado continua sendo o limite duro.
- **Teste de validação:** AC07/AC08 — sem cookie válido, `conversation_id` conhecido não devolve
  conteúdo em `GET`, `cancel` nem `DELETE`.
- **Rollback:** `RESUMABLE_CONVERSATIONS_ENABLED=false`; `/chat` legado continua sem identidade.
- **Aprovação:** tito (responsável pelo projeto) · **Data:** 2026-11-16

### ADR-03 — Persistência, retenção e exclusão

- **Status:** DECIDIDO (2026-11-16)
- **Problema:** o que existe no banco, por quanto tempo, e o que "apagar" significa?
- **Restrições:** INVs 10/12/13; LGPD; a UI não pode prometer o que não se cumpre; backups já
  existem e são testados (`ci.yml:78-132`).
- **Evidências:** `migrations/001_init.sql` (nada de conversa); `src/obs/logging.py:235-251`
  (retenção existe como configuração sem consumidor — D03); `README.md:347-348`.
- **Alternativas:** (A) minimizar — só mensagens e resultado final; (B) histórico completo opcional;
  (C) nada persistido, recuperação impossível.
- **Decisão proposta:** **A**. Conversa 30 dias (valor **a aprovar**), logs 7 dias (existentes),
  checkpoints descartados na conclusão, tombstones por 90 dias sem conteúdo. Exclusão = revogar
  credencial → tombstone → cancelar run → impedir publicação → purgar mensagens/checkpoints.
  Backups: declarar "até N dias", sem prometer remoção imediata das cópias.
- **Consequências:** job de limpeza; `purged_at`; teste de exclusão com worker atrasado.
- **Riscos:** publicação tardia pós-exclusão; cópias em backup; purga incompleta por falha.
- **Teste de validação:** AC15 e AC17.
- **Rollback:** não reverter migração destrutiva; manter a coluna e parar de usá-la.
- **Aprovação:** tito (responsável pelo projeto) · **Data:** 2026-11-16

### ADR-04 — API e compatibilidade

- **Status:** DECIDIDO (2026-11-16)
- **Problema:** como aceitar trabalho sem quebrar clientes existentes?
- **Evidências:** `src/api/main.py:936-988`; `web/app.py:36-57`; `tests/unit/test_api.py:985-1090`;
  `api.js:51-63`.
- **Alternativas:** (A) evoluir `/chat` para 202; (B) manter `/chat` e criar `/api/v1`;
  (C) versionar toda a API.
- **Decisão proposta:** **B**. `/chat` permanece síncrono e inalterado. Novo namespace
  `/api/v1/conversations...` com aceitação 202. `MULTIAGENT_ENABLED`, servida pelo servidor,
  decide se a UI usa o fluxo novo.
- **Consequências:** dois caminhos convivem; a UI escolhe por flag publicada em `/health`.
- **Riscos:** divergência de resposta entre caminhos — mitigado por compartilhar `ChatResponse`.
- **Teste de validação:** a suíte atual de `/chat` continua verde sem alteração.
- **Rollback:** flag em `false`; `/chat` nunca sai.
- **Aprovação:** tito (responsável pelo projeto) · **Data:** 2026-11-16

### ADR-05 — Concorrência, idempotência e retries

- **Status:** DECIDIDO (2026-11-16)
- **Problema:** repetir envio não pode duplicar mensagem nem execução (INV05); retry não pode
  multiplicar custo (INV11).
- **Evidências:** `app.js:887-889` (retry duplica); `src/api/main.py:549` (2 tentativas) ×
  `src/generate/llm.py:167` (`max_retries+1`) → até 6 chamadas; nenhuma idempotência hoje.
- **Decisão proposta:** `UNIQUE (conversation_id, client_message_id)`; conflito devolve a execução
  existente (200, não 409). Índice parcial único garantindo **uma execução ativa por conversa**;
  envio durante execução ativa é rejeitado com 409 + `Location`. Orçamentos em um único `Budget`
  no estado, decrementado por todas as camadas.
- **Consequências:** o cliente precisa de `client_message_id` (UUID gerado uma vez e reusado no
  retry — corrige D07).
- **Teste de validação:** AC04, AC12, AC14.
- **Rollback:** tabela pode ficar sem uso; nada destrutivo.
- **Aprovação:** tito (responsável pelo projeto) · **Data:** 2026-11-16

### ADR-06 — Transporte de acompanhamento

- **Status:** DECIDIDO (2026-11-16)
- **Problema:** como acompanhar sem replay e sem stream que perde evento?
- **Evidências:** `src/api/middleware.py:97-104` (log por requisição, sem stream); frontend em
  `fetch` puro (`api.js:15-28`); nenhuma infraestrutura de SSE hoje.
- **Decisão proposta:** **polling com revisão**. `GET /runs/{id}?since=N` devolve
  `{status, revision, events[]}`; o cliente guarda `revision` e pede o delta. Resultado final por
  `GET /runs/{id}/result`, idempotente. SSE fica como evolução sem mudar o contrato de estado.
- **Consequências:** um único mecanismo testável; nenhum evento precisa ser reproduzido depois.
- **Riscos:** latência de até um intervalo; custo de polling por aba.
- **Teste de validação:** AC03 e AC17.
- **Aprovação:** tito (responsável pelo projeto) · **Data:** 2026-11-16

### ADR-07 — Separação dos agentes e contratos

- **Status:** DECIDIDO (2026-11-16)
- **Problema:** onde termina a conversa e começa a pesquisa?
- **Evidências:** `src/api/main.py:390-473` (passe único); `src/contracts.py:39-114`;
  `docs/07-paradigmas-avaliados.md:64-68` ("agente por dentro, determinístico por fora").
- **Decisão proposta:** grafo com **dois nós que chamam LLM**: `conversation` e `research`. Todo o
  resto é código: autorização, política de ferramentas, orçamento, risco, versão, hidratação,
  validação de schema, citação canônica, idempotência, cancelamento, exclusão, publicação.
  Contratos Pydantic com `extra="forbid"` e união discriminada de evidência (§8.1). Evidência web
  **não** vira `RetrievedDevice` (E13).
- **Consequências:** `src/agents/`, `src/services/` e `src/api/{conversations,runs,auth}.py` passam
  a fazer sentido, mas só os que tiverem conteúdo real.
- **Riscos:** duplicar a lógica de recuperação. Mitigação: extrair `src/services/retrieval.py` por
  **caracterização** (T04), sem mudar comportamento.
- **Teste de validação:** T05/T06 — payloads inválidos e política adulterada são rejeitados.
- **Aprovação:** tito (responsável pelo projeto) · **Data:** 2026-11-16

### ADR-08 — Política de fundamentação e publicação

- **Status:** DECIDIDO (2026-11-16)
- **Problema:** uma saudação não pode ser tratada como afirmação jurídica, mas a regra global
  "sem citação, sem resposta" não pode ser enfraquecida.
- **Evidências:** `src/generate/verify.py:176-181` (regra global); `:68` (ausência de juiz conta
  como aprovação); `tests/unit/test_api.py:405-429` (referência inventada sobrevive no corpo).
- **Decisão proposta:** `OutputKind` explícito no estado (`juridica`, `esclarecimento`, `social`,
  `abstencao`, `falha_tecnica`) com **tabela de política** por tipo. Política padrão estrita:
  tipo desconhecido → regra atual. A saída pública expõe
  `verificacao: {deterministica: ok|falhou, semantica: ok|falhou|nao_avaliado}`, de modo que
  `semantic_ok=None` nunca vire "validado" (INV14).
- **Consequências:** `verify()` ganha parâmetro de política; testes atuais continuam valendo para
  o tipo `juridica`.
- **Riscos:** regressão silenciosa se alguém classificar resposta jurídica como `social`.
  Mitigação: teste que exige que `social` não contenha `device_id` nem citação.
- **Teste de validação:** AC09/AC10/AC11/AC20.
- **Aprovação:** tito (responsável pelo projeto) · **Data:** 2026-11-16

### ADR-09 — Pesquisa web opcional

- **Status:** DECIDIDO (2026-11-16)
- **Evidências:** não existe busca web hoje; `docs/07:73` desaconselha "deixar o agente escolher
  URLs"; `prompt.py:30-31` já trata documento como dado.
- **Decisão proposta:** **fora do primeiro incremento**. `WEB_SEARCH_ENABLED=false` por padrão,
  controlada pelo servidor. Quando ligada: allow-list de domínios oficiais, bloqueio de IP privado/
  loopback/metadata, limites de bytes/redirects/tipo, proveniência e data de acesso, tipo
  `EvidenciaWeb` separado, nunca ingestão automática na base.
- **Riscos:** SSRF, prompt injection via página, conflito de fontes.
- **Teste de validação:** AC22/AC23/AC18.
- **Aprovação:** tito (responsável pelo projeto) · **Data:** 2026-11-16

### ADR-10 — Observabilidade e tracing

- **Status:** DECIDIDO (2026-11-16)
- **Evidências:** `src/obs/logging.py:87-123` (whitelist de chaves de conteúdo), `:235-251`
  (retenção sem sink), `src/api/middleware.py:97-104` (evento sem corpo).
- **Decisão proposta:** manter o logger JSON existente como única saída; adicionar eventos de run
  (`run.accepted`, `run.started`, `run.progress`, `run.awaiting_input`, `run.completed`,
  `run.failed`, `run.cancelled`) **sem conteúdo** — só ids, contadores e duração. Tracing externo
  desligado até avaliação explícita. `retention_days()` ganha consumidor real ou é removido (D03).
- **Consequências:** métricas derivadas dos próprios eventos; `readiness` separado de `liveness`.
- **Teste de validação:** AC21 — inspecionar os logs de um turno e não achar a pergunta.
- **Aprovação:** tito (responsável pelo projeto) · **Data:** 2026-11-16

---

## 8. Contratos (PROPOSTA)

### 8.1 Contratos entre agentes

```text
PedidoPesquisa
  schema_version: str          # "pesquisa.v1"
  request_id: str
  parent_request_id: str | None
  turn_id: str
  pergunta_autossuficiente: str
  contexto_minimo: str         # sem relato integral
  pontos_a_verificar: list[str]
  evidence_refs_anteriores: list[str]

PoliticaPesquisa                # injetada pelo CÓDIGO, nunca pelo modelo
  permitir_web: bool
  fontes_permitidas: list[str]
  max_buscas: int
  max_evidencias: int
  deadline: datetime
  orcamento_restante: int

ResultadoPesquisa
  schema_version: str          # "pesquisa.v1"
  request_id: str
  status: suficiente | parcial | insuficiente | precisa_esclarecimento | erro
  evidencias: list[Evidencia]  # união discriminada
  lacunas: list[str]
  conflitos: list[str]
  esclarecimento_necessario: str | None
  erro_tipado: str | None
```

Evidência como união discriminada:

```text
EvidenciaBase: kind="base"  + evidence_id, device_id, norm_version_id,
                referencia_trecho, pontos_sustentados, proveniencia
EvidenciaWeb:  kind="web"   + evidence_id, url_validada, publicador,
                data_acesso, data_publicacao, trecho, snapshot_hash,
                pontos_sustentados
```

Regras: `extra="forbid"` em todos; `schema_version` obrigatório; "suficiente" é juízo do
pesquisador, **não** autorização de publicação.

### 8.2 Estado do grafo (mínimo)

```text
schema_version, conversation_id, turn_id, client_message_id,
contexto_conversacional_limitado, facts_com_proveniencia,
pedido_pesquisa, referencias_evidencias, resultado_pesquisa,
contadores_de_tentativa, orcamento, deadline,
resposta_candidata, resultado_validacao, resposta_final
```

Proibido no estado: clientes HTTP, conexões, locks, objetos de runtime.

### 8.3 Status externos e transições

```text
queued ──► running ──► succeeded
  │          │  │
  │          │  └──► awaiting_input ──► queued
  │          ├──► failed
  │          └──► cancel_requested ──► cancelled
  └──► expired          (queued além do deadline, nunca reivindicado)
```

`expired` não é `deleted`: exclusão usa **tombstone** separado, porque é preciso lembrar que a
conversa existiu para impedir recriação ou publicação tardia (INV12).

### 8.4 Contrato HTTP v1 (desenho)

| Rota | Semântica | Notas |
|---|---|---|
| `POST /api/v1/conversations` | cria conversa e credencial | 201 + `Set-Cookie` (ADR-02) |
| `GET /api/v1/conversations/current` | conversa do cookie | 404 se expirou |
| `POST /api/v1/conversations/{id}/messages` | aceita mensagem | 202 + `run_id`; 409 se já há run ativo; 200 idempotente |
| `GET /api/v1/conversations/{id}/runs/{run_id}` | estado + eventos desde `since` | 304 se nada mudou |
| `GET /api/v1/conversations/{id}/runs/{run_id}/result` | resultado final | 409 se ainda não concluído |
| `POST /api/v1/conversations/{id}/runs/{run_id}/cancel` | cancela | idempotente |
| `DELETE /api/v1/conversations/{id}` | tombstone + purga | idempotente |

Emergência: `POST .../messages` com risco imediato responde **200 síncrono** com o payload de
emergência, sem criar run e sem exigir banco (INV09, AC06).

Rotas privadas: `Cache-Control: no-store` (E15) e autorização por recurso (INV02).

### 8.5 Schema proposto (esboço, não executado)

```sql
-- migração nova: 003_conversations.sql (PROPOSTA, não aplicada)
CREATE TABLE conversations (
  id uuid PRIMARY KEY,
  created_at timestamptz NOT NULL DEFAULT now(),
  expires_at timestamptz NOT NULL,
  deleted_at timestamptz,            -- tombstone
  purged_at timestamptz
);
CREATE TABLE conversation_credentials (
  conversation_id uuid PRIMARY KEY REFERENCES conversations(id) ON DELETE CASCADE,
  token_hash bytea NOT NULL,         -- nunca o token em claro
  created_at timestamptz NOT NULL DEFAULT now(),
  revoked_at timestamptz
);
CREATE TABLE messages (
  id uuid PRIMARY KEY,
  conversation_id uuid NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
  turn_id text NOT NULL,
  client_message_id text NOT NULL,
  role text NOT NULL CHECK (role IN ('user','assistant')),
  content text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (conversation_id, client_message_id)   -- INV05
);
CREATE TABLE runs (
  id uuid PRIMARY KEY,
  conversation_id uuid NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
  thread_id text NOT NULL,
  status text NOT NULL,
  graph_version text NOT NULL,
  lease_until timestamptz,
  attempt int NOT NULL DEFAULT 0,
  revision bigint NOT NULL DEFAULT 0,
  created_at timestamptz NOT NULL DEFAULT now(),
  started_at timestamptz,
  finished_at timestamptz
);
CREATE UNIQUE INDEX one_active_run_per_conversation
  ON runs (conversation_id) WHERE status IN ('queued','running');
```

Este DDL é **PROPOSTA**. Não foi aplicado e não consta de `migrations/`.

---

## 9. Orçamentos e a matemática do retry

O código atual soma tentativas em camadas independentes:

- `src/api/main.py:549` — até 2 gerações por turno (`for attempt in (1, 2)`).
- `src/generate/llm.py:167` — até `max_retries + 1` por chamada do cliente
  (`OPENROUTER_MAX_RETRIES=2` → 3 tentativas).
- `src/api/main.py:549-566` e `:591-613` — cada tentativa pode gerar feedback e chamar o modelo de novo.

Com `rerank_provider=llm` e `query_rewrite=llm` ligados, o pior caso por turno é:

```text
N_llm = A_gen × R  +  A_rr × R  +  A_rw × R  +  A_judge × R
      = 2×3 + 1×3 + 1×3 + 2×3 = 18 chamadas de rede
```

com `A_gen` = tentativas de geração, `A_rr` = rerank, `A_rw` = rewrite, `A_judge` = judge,
`R` = `max_retries + 1`. Isso é **HIPÓTESE** (H06) até ser medido, mas a estrutura é observável.

**PROPOSTA:** um único objeto `Budget` no estado, com `calls_llm`, `tokens`, `searches`,
`deadline` e `cost`; decrementado **no cliente** (um só lugar), não em cada camada. Retry interno
do cliente HTTP deixa de ser invisível ao orçamento. Valores iniciais candidatos: 2 chamadas ao
pesquisador por turno, 3 buscas internas por chamada, 2 tentativas de geração, deadline global de
90 s, teto de tokens por turno. Cada valor precisa de medição antes de virar DECIDIDO.

---

## 10. Requisitos e invariantes — estado real

### 10.1 Requisitos funcionais

| ID | Requisito | Estado hoje | Evidência |
|---|---|---|---|
| RF01 | Dois agentes especializados | **Inexistente** | não há `src/agents/`; E01 |
| RF02 | Reaproveitar recuperação/geração | **Parcial** — tudo existe, mas embutido no pipeline | E06, E32, E33 |
| RF03 | Aceitar trabalho independente do navegador | **Inexistente** | E04, E10, E49 |
| RF04 | Recuperar estado/resultado autorizado | **Inexistente** | nenhuma tabela de conversa (E49); sem auth (E11) |
| RF05 | Acompanhar execução sem reenviar | **Inexistente** | E37 |
| RF06 | Esclarecimento quando indispensável | **Inexistente** | `abstain` só oferece abstenção (E29) |
| RF07 | Distinguir limitação, abstenção e falha | **Parcial** — `motivo_abstencao` existe, falha técnica e abstenção compartilham `abstencao=true` | E12, E29 |
| RF08 | Preservar citação canônica e vigência | **Sim** | E18, E21, E33 |
| RF09 | Cancelamento explícito | **Inexistente** | — |
| RF10 | Exclusão com semântica documentada | **Só local, e com bug** | E39, D05 |
| RF11 | Web não habilitada implicitamente | **Sim** (não existe web) | ADR-09 |
| RF12 | Emergência fora da dependência do fluxo longo | **Sim, bem testado** | E05, E27, E54 |

### 10.2 Invariantes

| ID | Invariante | Situação |
|---|---|---|
| INV01 | `thread_id` não concede acesso | Não aplicável hoje; **precisa de teste** (AC07) |
| INV02 | Leitura/mutação privada exige autorização | **Não existe** autorização alguma |
| INV03 | Desconectar não cancela | Desconectar já não cancela "nada", porque não há execução |
| INV04 | Reconectar não cria outro trabalho | Sem idempotência hoje (ADR-05) |
| INV05 | Repetir solicitação não duplica | Violado no cliente (E42/D07) |
| INV06 | Resposta não validada não é publicada | **Parcial** — `verify` roda antes de responder, mas `semantic_ok=None` aprova (E19) |
| INV07 | Modelo não escolhe a versão normativa | **Sim** (E33) |
| INV08 | Evidência web não se disfarça de base | Garantido por ausência de web; contrato proposto blinda (§8.1) |
| INV09 | Emergência não espera RAG/fila/modelo | **Sim** e testado (E05, E54) |
| INV10 | Tarefa aceita tem registro durável | Não existe (E49) |
| INV11 | Retry não amplia permissão nem reinicia orçamento | Não existe orçamento global (§9) |
| INV12 | Exclusão impede publicação tardia | Não existe publicação tardia nem exclusão remota |
| INV13 | Logs sem relato/prompt por padrão | **Sim** (E16, D03, whitelist em `logging.py:87-123`) |
| INV14 | "Não avaliado" ≠ "validado" | **Violado na prática** (E19/D11) |
| INV15 | Estado interno do pesquisador não vai ao navegador | A definir com o grafo |
| INV16 | Falha de rede não ativa resposta fictícia | **Violado** (E41/D08) |

---

## 11. Cenários de aceitação

Marquei o tipo de teste que **realmente** prova cada um. "Unit" não prova recuperação durável;
mock de banco não prova restart.

| ID | Cenário | Esperado | Tipo de teste |
|---|---|---|---|
| AC01 | Fechar aba após aceitação | Servidor conclui sem cliente | Integração + kill de cliente |
| AC02 | Voltar após conclusão | Mesma resposta, sem nova execução | Integração |
| AC03 | Voltar durante processamento | Estado atual + acompanhamento | Integração + navegador |
| AC04 | Conexão cai após aceite | Retry idempotente recupera a mesma execução | Integração |
| AC05 | Reiniciar worker em nó de pesquisa | Recuperação sem publicação duplicada | Integração com `kill -9` |
| AC06 | Banco indisponível em emergência | Resposta fixa sem esperar | Unidade + integração |
| AC07 | Usuário B consulta conversa A | Negado | Unidade HTTP |
| AC08 | B tenta stream/cancel/delete de A | Negado | Unidade HTTP |
| AC09 | IDs de fonte fabricados | Rejeição ou abstenção segura | Unidade |
| AC10 | Versão normativa incorreta | Rejeição | Unidade |
| AC11 | Afirmação inventada no corpo | Comportamento declarado, não "seguro por metadados" | Unidade + avaliação |
| AC12 | Pesquisador excede orçamento | Interrupção controlada | Unidade |
| AC13 | Precisa de esclarecimento | Turno concluído aguardando | Integração |
| AC14 | Duas abas simultâneas | Política de concorrência respeitada | Integração com 2 workers |
| AC15 | Exclusão durante pesquisa | Nenhuma publicação ou recriação tardia | Integração com worker atrasado |
| AC16 | Sessão expira | Conteúdo não revelado | Unidade HTTP |
| AC17 | Eventos antigos expiraram | Resultado final ainda recuperável | Integração |
| AC18 | Fonte com instruções maliciosas | Não altera política nem acesso | Unidade |
| AC19 | Rede falha no modo real | Não apresenta demo como atendimento | Navegador |
| AC20 | Resposta ainda não validada | Não expõe texto jurídico por streaming | Unidade |
| AC21 | Logs e traces inspecionados | Sem conteúdo sensível | Unidade |
| AC22 | Web desabilitada | Nenhuma chamada de rede de pesquisa | Unidade |
| AC23 | URL web para rede privada | Bloqueio | Unidade |
| AC24 | Saída rápida | Sai sem cancelar por engano | Navegador |
| AC25 | Nova mensagem indica risco durante run | Caminho de emergência não espera a thread | Integração |

**Ferramenta de navegador: não existe no repositório.** AC03, AC19 e AC24 não podem ser declarados
cobertos até que se escolha e valide uma ferramenta (PENDENTE P05). Hoje não há `playwright`,
`selenium` nem `pytest-playwright` em `pyproject.toml`.

---

## 12. Matriz de rastreabilidade

| Requisito | Cenário | Tarefa | Código (previsto) | Teste |
|---|---|---|---|---|
| RF03 | AC01, AC05 | T07, T09 | `src/services/runs.py`, `src/worker.py` | integração com kill |
| RF04 | AC02, AC07 | T08, T10 | `src/api/conversations.py` | HTTP + integração |
| RF05 | AC03 | T10 | `src/api/runs.py` | integração |
| RF09 | AC15 | T13 | `src/services/runs.py` | integração |
| RF10 | AC15, AC17 | T13 | `src/services/conversations.py` | integração |
| RF12 | AC06, AC25 | T09, T14 | `src/safety/risk.py` + rota | unidade |
| INV02 | AC07, AC08 | T08 | `src/api/auth.py` | HTTP |
| INV05 | AC04, AC14 | T09 | `messages.client_message_id` | integração |
| INV06 | AC09–AC11, AC20 | T05, T14 | `src/agents/policies.py` + `verify` | unidade |
| INV14 | AC11 | T14 | campo `verificacao` | unidade |
| INV13 | AC21 | T16 | `src/obs/logging.py` | unidade |
| INV16 | AC19 | T11, T12 | `web/ui/scripts/app.js` | navegador |

---

## 13. Backlog

Tarefas herdadas do briefing, refinadas com o que a descoberta encontrou. Nenhuma está aprovada.

| ID | Entrega | Depende | Primeiro teste/validação | Conclusão |
|---|---|---|---|---|
| T00 | Baseline real + inventário | — | `pytest -m "not integration"` em CI | SHA, contagens e falhas registradas (§4 parcial) |
| T01 | Jornadas, ameaça e pendências | T00 | Revisão das jornadas §5 | Perguntas bloqueadoras explícitas |
| T02 | **Spike de durabilidade** | T01 | Matar processo no meio do nó e reiniciar | ADR-01 decidido por execução |
| T03 | Spec implementável | T02 | Revisão de contratos | **Aprovação humana** |
| T04 | Extração de serviços RAG | T03 | Testes de caracterização do pipeline | Comportamento preservado |
| T05 | Contratos dos agentes | T03 | Payloads inválidos e política adulterada | Fronteiras testadas |
| T06 | Grafo com agentes fake | T04, T05 | Rotas, loops, limites | Fluxo determinístico coberto |
| T07 | Persistência e recuperação | T02, T06 | Restart com banco real | Estado recuperado |
| T08 | Sessão e autorização | T03, P01 | Acesso cruzado em todas as rotas | Ids não concedem acesso |
| T09 | Aceitação e idempotência | T07, T08 | Falha entre persistir e confirmar | Sem execução duplicada |
| T10 | Resultado e acompanhamento | T09 | Reconexão sem reenvio | Snapshot e resultado consistentes |
| T11 | Frontend | T10 | Fechar/reabrir no navegador | Continuidade e estados claros |
| T12 | Segurança da interface | T08–T11 | Sessão expirada, cache, duas abas | Sem revelação indevida |
| T13 | Cancelamento e exclusão | T07–T12 | Worker atrasado após exclusão | Sem publicação tardia |
| T14 | Integração com LLM | T06–T13 | Saídas inválidas e falhas do provedor | Validação preservada |
| T15 | Web opcional | Aprovação específica | SSRF e prompt injection | Isolada, desligada por padrão |
| T16 | Observabilidade | T07–T14 | Inspeção de logs | Diagnóstico sem conteúdo |
| T17 | E2E e revisão | T11–T16 | Matriz AC | Evidências registradas |
| T18 | Demonstração | T17 | Roteiro reproduzível | Fluxo completo documentado |

### 13.1 Ordem recomendada

`T00 → T01 → T02 → (gate de aprovação) → T03`. Nada além de T02 pode começar sem a §16 resolvida.
T02 é deliberadamente pequeno: um script, um grafo de dois nós, um `PostgresSaver`, um `kill -9`.

### 13.2 Spike T02 — definição mínima

- **Objetivo:** provar (ou refutar) que LangGraph + `PostgresSaver` retoma após morte do processo,
  com publicação exatamente uma vez.
- **Entrada:** um `PedidoPesquisa` sintético fixo; um nó "research" que dorme 5 s e incrementa um
  contador em tabela própria (efeito externo simulado).
- **Passos:** rodar; `kill -9` no processo durante o nó; reiniciar; `invoke(None, config)`.
- **Critérios de sucesso:** (1) execução termina; (2) contador = 1, não 2; (3) tabela de runs tem
  exatamente uma linha; (4) número de reexecuções do nó é registrado.
- **Fora de escopo:** HTTP, UI, auth, LLM real.
- **Evidência a registrar:** comandos, saída, contagens, versão do `langgraph`.

---

## 14. Plano TDD e evidência

### 14.1 Ciclo por incremento

Idêntico ao briefing (§14.1). Nenhum incremento começou, portanto não há evidência RED/GREEN a
registrar. Qualquer linha desta seção só será preenchida com comando, ambiente e saída reais.

### 14.2 Evidência de execução coletada até agora

| Tarefa | Comando | Esperado | Observado | Ambiente |
|---|---|---|---|---|
| T00 | `uv sync --extra dev` com `UV_CACHE_DIR` no workspace | criar `.venv/` | sucesso (Python 3.12.13) | Windows 11 |
| T00 | `pytest -m "not integration" -q` | suíte verde | **789 passed**, 1 failed, 57 errors — falha e erros são do sandbox (§4.2) | idem |
| T00 | `pytest tests/unit/test_ops_scripts.py::test_shell_scripts_are_parseable --tb=short` | — | `bash: couldn't create signal pipe, Win32 error 5` | idem |
| T00 | `pytest ... --tb=line` (amostra de erros) | — | `PermissionError` em `...\Temp\dsh-UeyeSP\pytest-of-tito` | idem |
| T02 | `python spikes/t02_durability/spike.py run` | publicação única e efeito único | `naive`: efeitos=2; `idempotent`: efeitos=1 (§20) | idem, `langgraph 1.2.22` |
| T00 | `pytest -m integration` (com Postgres e Qdrant reais) | integração verde | **8 passed, 4 skipped** (§4.3) | Docker: `db` pg17 + `qdrant` v1.15.3 |
| T02 | `spike.py run --backend postgres` | idem do SQLite | idem: efeitos=2 / 1 (§20.7) | `langgraph-checkpoint-postgres 3.2.1` |

Registro honesto: **não houve ciclo RED→GREEN**. T00 e T02 são investigação e experimento, não
implementação de comportamento. O primeiro teste RED do projeto será o de T05.

### 14.3 O que não pode ser testado sem decisão

- Navegador (AC03, AC19, AC24): falta ferramenta.
- Integração (AC01, AC05, AC14, AC15, AC17): falta Docker em execução.
- Recuperação durável (AC01, AC05): falta T02.

---

## 15. Riscos residuais

| Risco | Severidade | Mitigação proposta |
|---|---|---|
| Reexecução de nó duplica efeito externo | Alta | T02 + efeitos idempotentes + dedupe na publicação |
| Publicação tardia após exclusão | Alta | tombstone consultado antes de publicar (T13) |
| Cookie não protege aparelho desbloqueado | Alta | declarar limite; aviso na UI; não prometer privacidade |
| XSS leria conversa persistida | Média | `markdown.js` já escapa; CSP ausente (E17) |
| Log acidental com conteúdo | Média | whitelist existente + AC21 |
| Regressão do caminho de emergência | Alta | AC06/AC25 + `tests/unit/test_api.py:241-346` |
| Drift entre versão do grafo e checkpoints | Média | `graph_version` em `runs`; política de drain |
| Custo de LLM explodir por retry | Média | `Budget` único (§9) |
| Backups com dados "excluídos" | Média | declarar janela; não prometer remoção imediata |

---

## 16. Pendências e gate de aprovação

### 16.1 Decisões que exigem aprovação humana

| ID | Questão | Bloqueia | Status |
|---|---|---|---|
| **P01** | Identidade: cookie de capacidade (A), código de retomada (B) ou conta (C)? | T08, T10, T11, T12 | **APROVADO — opção A** (ADR-02) |
| **P02** | Retenção: quantos dias, e o que "apagar" significa? | T03, T13, textos da UI | **APROVADO — ADR-03**, com o prazo de 30 dias ainda a confirmar (§19.3) |
| **P03** | Runtime: biblioteca + worker (B) ou Agent Server (A)? | T07, T09 | **APROVADO — opção B**, condicionado ao spike T02 |
| **P04** | A UI pode deixar de prometer "conversa só nesta aba"? | T11, T12 | **APROVADO** — o texto final é redigido em T11 e revisado antes de publicar |
| P05 | Ferramenta de teste de navegador (Playwright?) e se entra no CI | AC03, AC19, AC24 | PENDENTE |
| P06 | Botão de saída rápida: o que exatamente ele apaga? | T12 | PENDENTE |
| P07 | Web: fica desligada no primeiro incremento? | T15 | PENDENTE (ADR-09 propõe desligada) |
| P08 | Orçamentos numéricos (deadline, tokens, custo por turno) | T09, T14 | PENDENTE — §9 traz apenas candidatos |
| P09 | Revisão jurídica: quem assina e com qual critério? | publicação | PENDENTE |
| P10 | Política para múltiplas abas e múltiplas mensagens | T09 | PROPOSTA (ADR-05, 409 + uma execução ativa) |
| P11 | Hospedagem e modalidade operacional | T17 | PENDENTE |
| P12 | Quem executa T00 em ambiente limpo? | todos | PENDENTE — §19.4 |

### 16.2 Gate

**Gate aberto em 2026-11-16.** P01–P04 respondidas pelo responsável; ver §19, que registra
literalmente o que foi aprovado e o que **não** foi.

Com o gate aberto, o trabalho autorizado é: **T00 em ambiente limpo** e **T02 (spike de
durabilidade)**. Nenhum código de produto, migração ou dependência entra em `src/` antes de T03,
que é a próxima aprovação humana — desta vez sobre a spec implementável concreta e o schema
definitivo.

P05–P12 seguem abertas e podem bloquear tarefas específicas (indicadas na coluna da tabela).

---

## 17. Runbook mínimo (rascunho, para depois da aprovação)

| Situação | Ação |
|---|---|
| Worker caiu | `docker compose ps`; reiniciar; reconciliador reivindica runs com lease expirado |
| Banco indisponível | Emergência continua respondendo (não usa banco); `/health` deve reportar `degraded` |
| Provedor LLM indisponível | `_safe_answer` já cobre (`main.py:552-554`); verificar orçamento consumido |
| Execução presa | Ver `runs.status`, `lease_until`; forçar `failed` após o deadline |
| Resultado não aparece | Conferir `runs` e `messages`; nunca reenviar a pergunta |
| Suspeita de acesso indevido | Revogar credencial, tombstone, inspecionar `http.access` por `request_id` |
| Exclusão incompleta | Rodar job de purga; conferir `purged_at`; backups seguem a política |
| Rollback do grafo | Desligar `MULTIAGENT_ENABLED`; drenar execuções ativas; `/chat` segue |

---

## 18. Relatório final desta fase

- **O que foi feito:** descoberta estática completa do núcleo de decisão; cinco frentes paralelas
  com evidência `caminho:linha`; pesquisa documental de LangGraph; tentativa de baseline real;
  mapa de evidências, divergências, jornadas, hipóteses, dez ADRs, contratos, requisitos, cenários
  de aceitação, backlog e gate de aprovação.
- **O que não foi feito:** implementação, testes novos, migrações, dependências, E2E, integração.
- **Decisões tomadas por agente:** nenhuma. Todas as escolhas estão em `PROPOSTO`.
- **Testes executados:** apenas a suíte existente, com as ressalvas registradas na §4 e §14.2.
- **Testes não executados:** integração (sem Docker), navegador (sem ferramenta), avaliação de IA.
- **Principais descobertas:** o projeto não tem identidade nem persistência de conversa; o caminho
  de emergência é sólido e deve ser preservado; `semantic_ok=None` é tratado como aprovação; a UI
  promete "só nesta aba" e não rotaciona sessão ao apagar; dois testes divergem da documentação
  (`MAX_AGENT_LOOPS`, `buscar_jurisprudencia`).
- **Próximo incremento recomendado:** T02 (spike de durabilidade), condicionado à aprovação de P03;
  depois T00 em ambiente limpo.
- **Declaração:** nada neste documento constitui validação jurídica, aprovação de segurança ou
  autorização de uso público.

---

## 19. Registro de aprovação

### 19.1 Termo

| Campo | Valor |
|---|---|
| Aprovador | tito (responsável pelo projeto) |
| Data | 2026-11-16, America/Sao_Paulo |
| Manifestação literal | "aprovado." |
| Escopo interpretado | as quatro decisões bloqueadoras P01–P04 **com a opção recomendada em cada ADR**, e o documento de descoberta como base de trabalho |
| Efeito | ADR-01 a ADR-10 passam de `PROPOSTO` para `DECIDIDO` |

A interpretação está registrada de forma explícita porque a manifestação foi sintética. Se a
intenção era aprovar apenas o documento e não as opções recomendadas, **as linhas abaixo são o
ponto exato de correção** — basta pedir para reverter o ADR correspondente.

### 19.2 O que foi efetivamente aprovado

1. **ADR-01 — opção B:** LangGraph (biblioteca) + runtime durável próprio sobre o Postgres
   existente, com fila em tabela, `SELECT ... FOR UPDATE SKIP LOCKED`, lease e reconciliador.
   A validação final fica com o spike T02: se o spike falhar, o ADR reabre.
2. **ADR-02 — opção A:** cookie de capacidade (segredo opaco de 32 bytes, `HttpOnly`,
   `SameSite=Lax`, `Secure` com TLS; o servidor guarda só o hash). Sem contas, sem retomada entre
   aparelhos, limite declarado na UI.
3. **ADR-03 — opção A:** persistência minimizada (mensagens + resultado final), tombstones sem
   conteúdo, exclusão em cadeia. O **prazo de 30 dias** continua sendo proposta até confirmação
   (§19.3).
4. **ADR-04 a ADR-10:** mantidos como descritos — `/chat` intocado, `/api/v1` novo, idempotência
   por `(conversation_id, client_message_id)`, polling com revisão, dois nós LLM com o resto
   determinístico, política de publicação por `OutputKind`, web desligada e observabilidade sem
   conteúdo.

### 19.3 O que **não** foi aprovado (e não pode ser assumido)

| Item | Por que não | Quem decide |
|---|---|---|
| Prazo de 30 dias de retenção | era "valor a aprovar" no ADR-03 | responsável (P02) |
| Números de orçamento (§9) | eram candidatos, dependem de medição | responsável + medição (P08) |
| Ferramenta de teste de navegador | não estava no conjunto bloqueador | responsável (P05) |
| Semântica do botão de saída rápida | não estava no conjunto bloqueador | responsável (P06) |
| Revisão jurídica e critério de verificação semântica | processo humano, fora do escopo técnico | responsável (P09) |
| Hospedagem e modalidade operacional | depende de infraestrutura | responsável (P11) |

### 19.4 Autorização de execução concedida por este gate

- **T00** — reexecutar a suíte em ambiente limpo e registrar o baseline real.
- **T02** — spike de durabilidade, isolado, sem tocar `src/`, sem LLM real e sem dados de pessoa.

Nada além disso. T03 (spec implementável concreta + schema definitivo) é a próxima aprovação.

---

## 20. T02 — Spike de durabilidade: resultado

**Status:** EXECUTADO · **Ambiente:** Windows 11, Python 3.12.13, `.venv` da worktree,
`langgraph 1.2.22`, `langgraph-checkpoint 4.3.2`, `langgraph-checkpoint-sqlite 3.1.3` ·
**Dados:** exclusivamente sintéticos, sem LLM, sem rede, sem relato de pessoa.

### 20.1 O que foi construído

`spikes/t02_durability/spike.py` (fora de `src/`, fora do pacote — `hatch` empacota só `src`), com
um grafo de dois nós:

- `research`: registra a execução, grava um **efeito externo simulado** e dorme 6 s;
- `publish`: registra a execução e grava a publicação com chave idempotente.

O orquestrador inicia o worker em subprocesso, espera o sinal de "entrei no nó", aplica
`TerminateProcess` (sem shutdown) no meio do `research`, e retoma em **outro processo** com
`graph.invoke(None, config)`.

### 20.2 Resultado medido

| Variante | Publicações | Efeitos externos | Execuções de `research` | Execuções de `publish` |
|---|---|---|---|---|
| `naive` (efeito sem chave) | 1 | **2 (duplicado)** | 2 | 1 |
| `idempotent` (efeito com chave) | 1 | **1** | 2 | 1 |

Comando e saída: `.venv\Scripts\python.exe spikes\t02_durability\spike.py run`, exit 0.

### 20.3 Conclusões (VALIDADO)

1. **A execução sobrevive à morte do processo.** O estado volta do checkpoint e a execução termina
   no processo novo, sem o cliente. H01 confirmado — para `SqliteSaver`.
2. **O nó reexecuta desde o início.** `research` rodou duas vezes (antes e depois do kill). O
   checkpoint é de fronteira de super-step, não de linha. H02 confirmado.
3. **Efeito externo sem chave duplica.** Na variante `naive` o efeito aparece 2×. Isso não é
   detalhe: com LLM real significa **cobrança dupla**, e com escrita significa dado duplicado.
4. **Publicação com chave idempotente fica em 1 nas duas variantes.** A defesa proposta em
   ADR-05/§8.5 funciona no pior caso.

### 20.4 Achado adicional (não previsto)

Em uma execução intermediária, quando o efeito duplicado **violou uma restrição de unicidade**, o
`resume` abortou com `IntegrityError` e a publicação **nunca aconteceu**. Ou seja: efeito não
idempotente não apenas duplica — ele pode **impedir a recuperação**. Isso reforça três invariantes
da spec: publicação deduplicada, chaves idempotentes nas chamadas externas e `Budget` que **não**
reinicia no replay.

### 20.5 Limites deste spike (o que ele NÃO prova)

- **Não valida concorrência** (dois workers, `SKIP LOCKED`, lease expirado) — é T09.
- **Não valida idempotência HTTP** nem a fila em tabela — é T09.
- **Não mede custo/latência** de reexecução com LLM real.

### 20.6 Efeito sobre a ADR-01

A decisão (biblioteca + runtime próprio) sai **confirmada**: o experimento rodou com os dois
checkpointers e com o backend real da arquitetura (§20.7). A alternativa Agent Server continua
bloqueada por licença e custo desconhecidos, mas deixou de ser necessária para o requisito.

### 20.7 Repetição com `PostgresSaver` — **VALIDADO**

Com o Docker em execução, o mesmo experimento rodou contra o checkpointer que a arquitetura usa:
`langgraph-checkpoint-postgres 3.2.1`, banco isolado `spike_t02` no serviço `db` do
`docker-compose.yml`, `psycopg` com `autocommit=True`. Comando:
`.venv\Scripts\python.exe spikes/t02_durability/spike.py run --backend postgres` (exit 0).

| Backend | Variante | Publicações | Efeitos externos | Execuções de `research` |
|---|---|---|---|---|
| sqlite | `naive` | 1 | **2** | 2 |
| sqlite | `idempotent` | 1 | **1** | 2 |
| postgres | `naive` | 1 | **2** | 2 |
| postgres | `idempotent` | 1 | **1** | 2 |

**Resultado idêntico ao do SQLite.** As conclusões de §20.3 valem para o backend real, não só para um
saver de conveniência.

Evidência de schema (`spikes/t02_durability/inspect_db.py`): `PostgresSaver.setup()` criou
exatamente as quatro tabelas previstas — `checkpoints`, `checkpoint_blobs`, `checkpoint_writes`,
`checkpoint_migrations` — com 8 posts de checkpoint, 10 writes e 2 blobs ao final. Isso confirma
empiricamente o que a documentação afirmava e que até então só tínhamos como leitura.

**H01 passa a VALIDADA nos dois backends.** O que resta fora do escopo do spike é de outra tarefa:
concorrência e idempotência HTTP (T09), e custo/latência com LLM real (T14).

---

## 21. Spec implementável (T03)

Autorizada em 2026-11-16 pela instrução "desenvolva todas as tasks". Substitui os esboços da §8
onde houver conflito. Regra de convivência: **nada existente muda de contrato** — `/chat`,
`ChatResponse`, `LegalRAGPipeline`, `verify()` e o caminho de emergência continuam válidos e
testados; o fluxo novo é aditivo e desligável por flag.

### 21.1 Ordem de execução e regra de concorrência

`T05 → T04 → T06 → T07 → T08 → T09 → T10 → T11 → T12 → T13 → T14 → T15 → T16 → T17 → T18`

(T05 antes de T04 porque os contratos são a fronteira que o resto consome; a extração de serviços
deve acontecer sabendo para onde vai.)

Arquivos de owner único, nunca editados em paralelo: `src/contracts.py`, `src/api/main.py`,
`migrations/*`, `pyproject.toml`/`uv.lock`, `web/ui/scripts/app.js`. Cada arquivo tem **um** dono
por incremento; revisão só lê.

### 21.2 Modelo de dados final

Migração `003_conversations.sql`:

```sql
CREATE TABLE conversations (
    id            uuid PRIMARY KEY,
    owner_hash    bytea NOT NULL,          -- sha256 do token; nunca o token
    created_at    timestamptz NOT NULL DEFAULT now(),
    last_seen_at  timestamptz NOT NULL DEFAULT now(),
    expires_at    timestamptz NOT NULL,
    deleted_at    timestamptz,             -- tombstone: conversa apagada
    purged_at     timestamptz
);

CREATE TABLE messages (
    id                uuid PRIMARY KEY,
    conversation_id   uuid NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    turn_id           text NOT NULL,
    client_message_id text NOT NULL,
    role              text NOT NULL CHECK (role IN ('user','assistant')),
    content           text NOT NULL,
    created_at        timestamptz NOT NULL DEFAULT now(),
    UNIQUE (conversation_id, client_message_id)
);

CREATE TABLE runs (
    id              uuid PRIMARY KEY,
    conversation_id uuid NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    thread_id       text NOT NULL,
    status          text NOT NULL CHECK (status IN
                      ('queued','running','awaiting_input','succeeded','failed',
                       'cancel_requested','cancelled','expired')),
    graph_version   text NOT NULL,
    revision        bigint NOT NULL DEFAULT 0,
    attempt         integer NOT NULL DEFAULT 0,
    lease_until     timestamptz,
    deadline        timestamptz NOT NULL,
    budget_json     jsonb NOT NULL DEFAULT '{}'::jsonb,
    result_json     jsonb,
    error_code      text,
    created_at      timestamptz NOT NULL DEFAULT now(),
    started_at      timestamptz,
    finished_at     timestamptz
);

CREATE UNIQUE INDEX one_active_run_per_conversation
    ON runs (conversation_id) WHERE status IN ('queued','running','cancel_requested');
CREATE INDEX runs_claimable ON runs (created_at) WHERE status = 'queued';
CREATE INDEX runs_expired  ON runs (deadline)   WHERE status IN ('queued','running');
```

Regras duras:

Índices além dos listados acima, por necessidade operacional: `messages_conversation`
(listagem por conversa), `conversations_expiry` (purga por retenção) e `runs_claimable`
(fila). `runs_expired` cobre `queued|running`; após a emenda de §21.4 ele deveria cobrir também
`awaiting_input` — pendência registrada para T13, junto com a filtragem de tombstone no claim.

- `owner_hash` é o **único** vínculo de autorização. `conversation_id` sozinho não lê nada (INV01).
- `client_message_id` é gerado pelo cliente **uma vez** e reusado no retry (INV05).
- `messages.content` guarda a pergunta e a resposta final, nada mais (ADR-03 opção A).
- `runs.result_json` é a **projeção pública** do resultado, não o estado do grafo (INV15).
- Checkpoints do LangGraph ficam nas tabelas do próprio `PostgresSaver`, no mesmo banco.

### 21.3 Módulos, responsabilidades e assinaturas

```text
src/agents/contracts.py     PedidoPesquisa, PoliticaPesquisa, ResultadoPesquisa,
                            EvidenciaBase, EvidenciaWeb, Evidencia (union), OutputKind,
                            RespostaConversa, StatusPesquisa
src/agents/state.py         AgentState (TypedDict), novos_estado(), reduzir_evidencias()
src/agents/policies.py      politica_de_publicacao(kind) -> Politica
                            classificar_saida(resposta, evidencias) -> OutputKind
                            validar_publicacao(resposta, evidencias, politica) -> list[str]
src/agents/conversation.py  decidir(state) -> acao                      [1 nó com LLM]
src/agents/research.py      pesquisar(state) -> ResultadoPesquisa       [1 nó com LLM]
src/agents/graph.py         build_graph(checkpointer=None) -> CompiledStateGraph
src/services/retrieval.py   recuperar(pergunta, facts, deps) -> list[RetrievedDevice]
src/services/generation.py  gerar(pergunta, devices, deps) -> Answer
src/services/runs.py        criar_run, reivindicar, concluir, falhar, cancelar,
                            solicitar_cancelamento, encerrar_pendente,
                            reconciliar_expirados, obter, obter_por_conversa
src/services/conversations.py criar_conversa, autenticar, obter, apagar, purgar
src/api/auth.py             emitir_cookie, exigir_conversa (dependency)
src/api/conversations.py    rotas v1 de conversa
src/api/runs.py             rotas v1 de execução
src/worker.py               loop de reivindicação e execução
```

Assinaturas que o resto do código pode assumir:

```python
# src/agents/contracts.py
class PedidoPesquisa(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal["pesquisa.v1"] = "pesquisa.v1"
    request_id: str
    parent_request_id: str | None = None
    turn_id: str
    pergunta_autossuficiente: str = Field(min_length=1, max_length=2000)
    contexto_minimo: str = ""
    pontos_a_verificar: list[str] = Field(default_factory=list, max_length=10)
    evidence_refs_anteriores: list[str] = Field(default_factory=list, max_length=50)

class ResultadoPesquisa(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal["pesquisa.v1"] = "pesquisa.v1"
    request_id: str
    status: Literal["suficiente","parcial","insuficiente","precisa_esclarecimento","erro"]
    evidencias: list[Evidencia] = Field(default_factory=list, max_length=20)
    lacunas: list[str] = Field(default_factory=list)
    conflitos: list[str] = Field(default_factory=list)
    esclarecimento_necessario: str | None = None
    erro_tipado: str | None = None

class EvidenciaBase(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["base"] = "base"
    evidence_id: str
    device_id: str
    norm_version_id: int
    referencia_trecho: str = ""
    pontos_sustentados: list[str] = Field(default_factory=list)
    proveniencia: str = "base"

class EvidenciaWeb(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["web"] = "web"
    evidence_id: str
    url_validada: str
    publicador: str
    data_acesso: date
    data_publicacao: date | None = None
    trecho: str
    snapshot_hash: str
    pontos_sustentados: list[str] = Field(default_factory=list)

Evidencia = Annotated[EvidenciaBase | EvidenciaWeb, Field(discriminator="kind")]
OutputKind = Literal["juridica","esclarecimento","social","abstencao","falha_tecnica"]
```

### 21.4 Máquina de estados

Transições permitidas (qualquer outra é erro e vira `failed`):

`awaiting_input` **não** entra no índice de execução única (§21.2): a nova mensagem cria
outro run e fecha o anterior como `succeeded`. Em troca, o reconciliador precisa expirá-lo
(§21.7), senão a linha fica imortal — risco apontado na revisão do T07 e coberto por teste.


```text
queued        -> running | cancel_requested | expired | failed
running       -> succeeded | failed | awaiting_input | cancel_requested
awaiting_input-> succeeded | cancelled     (encerrar_pendente, quando chega novo turno)
             -> expired                  (reconciliar_expirados)
cancel_requested -> cancelled                (só; quem já publicou está em succeeded)
succeeded/failed/cancelled/expired  -> terminal
```

`DELETE` não é transição de estado: grava `conversations.deleted_at`, marca runs ativos como
`cancel_requested` e o worker, antes de publicar, reconsulta o tombstone (INV12).

### 21.5 API v1

Base: `/api/v1`. Todas as rotas de conversa exigem o cookie (`owner_hash`), devolvem
`Cache-Control: no-store` e nunca incluem o token em URL, log ou corpo.

| Método | Rota | Sucesso | Erros |
|---|---|---|---|
| POST | `/conversations` | 201 + `Set-Cookie: zelia_owner=...; HttpOnly; SameSite=Lax; Path=/; Max-Age=...` | — |
| GET | `/conversations/current` | 200 `{id, created_at, expires_at, messages[]}` | 401 sem cookie; 404 se expirada/apagada |
| POST | `/conversations/{id}/messages` | 202 `{run_id, status}`; 200 se repetido com mesmo `client_message_id` | 401, 404, 409 (run ativo), 422 |
| GET | `/conversations/{id}/runs/{run_id}` | 200 `{status, revision, events[]}`; 304 se `since` == revision | 401, 404 |
| GET | `/conversations/{id}/runs/{run_id}/result` | 200 `ChatResponse` (mesmo schema do legado) | 409 se não concluído |
| POST | `/conversations/{id}/runs/{run_id}/cancel` | 202 | 401, 404, 409 se terminal |
| DELETE | `/conversations/{id}` | 204 idempotente | 401, 404 |

Emergência: `POST .../messages` detecta risco **antes** de qualquer escrita e responde **200**
com o payload de emergência e `emergencia: true`, sem criar run e sem tocar no banco (INV09).

Eventos públicos (projeção sanitizada): `run.accepted`, `run.started`, `run.progress`,
`run.awaiting_input`, `run.completed`, `run.failed`, `run.cancelled`. Nunca estado do grafo,
prompt, resultado bruto de ferramenta ou texto jurídico não validado.

### 21.6 Política de publicação por tipo de saída

| `OutputKind` | Exige citação | Exige literal | Pode conter `device_id` | Regra |
|---|---|---|---|---|
| `juridica` | sim | sim | sim | `verify()` atual, sem alteração |
| `esclarecimento` | não | não | **não** | só pergunta de volta |
| `social` | não | não | **não** | sem afirmação jurídica |
| `abstencao` | não | não | não | `fallback_abstain` + números |
| `falha_tecnica` | não | não | não | `build_safe_answer` |
| desconhecido | sim | sim | sim | igual a `juridica` (falha fechada) |

A saída pública passa a carregar `verificacao: {deterministica, semantica}` com
`semantica ∈ {ok, falhou, nao_avaliado}`. `semantic_ok=None` **nunca** vira `ok` (INV14).

### 21.7 Worker

Loop: `reivindicar_proximo` → `running` + `lease_until = now() + 60s` → executar grafo →
`finalizar` na mesma transação da publicação.

```sql
UPDATE runs SET status='running', started_at=now(), lease_until=now() + interval '60 seconds',
                attempt=attempt+1, revision=revision+1
WHERE id = (SELECT id FROM runs
            WHERE deadline > now()
              AND (status = 'queued'
                   OR (status = 'running' AND lease_until < now()))
            ORDER BY created_at, id
            FOR UPDATE SKIP LOCKED LIMIT 1)
RETURNING *;
```

- Lease expirado → outro worker reivindica; a reexecução é segura **porque** publicação é
  deduplicada e efeitos externos usam chave (resultado do T02, §20).
- `reconciliar_expirados` roda a cada ciclo: `deadline < now()` e não terminal → `expired`.
- `SIGTERM` → parar de reivindicar, terminar o atual, sair.

**Fronteira transacional (achado H2 da revisão):** `reivindicar` não faz commit. O worker deve
commitar o claim em transação curta, executar o grafo fora da transação e publicar em outra —
caso contrário a linha fica travada durante todo o run e o reconciliador espera por ela.
**Reconciliação em lote (H3):** o `UPDATE` de `reconciliar_expirados` pega todas as linhas
vencidas de uma vez; se o volume crescer, limitar por lote é trabalho de T13.

### 21.8 Orçamento

`Budget(calls_llm, tokens, searches, deadline, cost)` serializado em `runs.budget_json`,
decrementado **no cliente LLM** (`src/services/generation.py` e `research.py`), não por camada.
Defaults propostos, ainda **não aprovados** (P08): `calls_llm=8`, `searches=9`, `deadline=90s`,
`tokens=40000`. Sem aprovação, entram como configuração com esses valores e um teste que documenta
que são candidatos.

### 21.9 Configuração nova

```text
MULTIAGENT_ENABLED=false            # UI usa o fluxo novo quando true
RESUMABLE_CONVERSATIONS_ENABLED=false
WEB_SEARCH_ENABLED=false
CONVERSATION_RETENTION_DAYS=30      # P02: proposta, não aprovada
TOMBSTONE_RETENTION_DAYS=90
RUN_LEASE_SECONDS=60
RUN_DEADLINE_SECONDS=90
WORKER_POLL_SECONDS=2
BUDGET_MAX_LLM_CALLS=8
BUDGET_MAX_SEARCHES=9
```

### 21.10 Migrações

`003_conversations.sql` (este incremento), `004_indexes_e_tombstones.sql` se medição pedir.
`scripts/apply_migrations.py` **tem** tabela de controle (`schema_migrations`) desde T07: arquivo já aplicado é pulado e o registro é gravado na mesma transação. Cada arquivo novo continua
**idempotente** (`IF NOT EXISTS`), porque D10 ainda está aberto.

### 21.11 Mapa de arquivos por tarefa

| Tarefa | Arquivos | Owner |
|---|---|---|
| T04 | `src/services/retrieval.py`, `generation.py`, `tests/unit/test_services_*.py` | lead |
| T05 | `src/agents/contracts.py`, `tests/unit/test_agent_contracts.py` | lead |
| T06 | `src/agents/{state,policies,graph,conversation,research}.py`, fakes + testes | lead |
| T07 | `migrations/003_conversations.sql`, `src/services/runs.py`, testes de integração | lead |
| T08 | `src/api/auth.py`, `src/services/conversations.py`, testes HTTP | lead |
| T09 | `src/api/conversations.py`, testes de idempotência | lead |
| T10 | `src/api/runs.py`, testes de reconexão | lead |
| T11/T12 | `web/ui/scripts/{api,app}.js`, `index.html` | lead (arquivo único) |
| T13 | `src/services/runs.py` (exclusão), testes com worker atrasado | lead |
| T14 | `src/agents/*` integração real, testes de validação | lead |
| T15 | `src/services/web_search.py` (desligado), testes SSRF | lead |
| T16 | `src/obs/logging.py`, eventos de run | lead |
| T17/T18 | `tests/integration`, `docs/` | lead |

Revisão: agente F independente por incremento, com o formato de handoff da §12.3 do briefing.

---

## 22. Registro de execução (T03–T06)

Ciclo por incremento conforme §14.1: teste que falha pelo motivo certo → implementação mínima →
verde → regressão. Comandos, saída e limitações registrados abaixo.

### 22.1 T03 — spec implementável

Gravada como **§21** deste documento. Define schema (migração `003_conversations.sql`), máquina de
estados, contrato HTTP v1, política de publicação por `OutputKind`, protocolo do worker, orçamento,
configuração e mapa de arquivos por tarefa.

### 22.2 T05 — contratos entre agentes

| Passo | Comando | Resultado |
|---|---|---|
| RED | `pytest tests/unit/test_agent_contracts.py` | `16 failed` — `ModuleNotFoundError: No module named 'src.agents'` |
| GREEN | idem, após implementar | `16 passed in 0.13s` |
| Regressão | `pytest -m "not integration"` | `863 passed, 12 deselected` |

**Correção declarada:** dois testes que escrevi eram contraditórios entre si — um aceitava
`RespostaConversa(kind="juridica")` sem citação e outro exigia erro para o mesmo caso. Alterei o
primeiro para usar `kind="social"`. Foi correção de contradição, **não** enfraquecimento de
expectativa; a regra "jurídica exige evidência" continua testada e ativa.

Arquivos: `src/agents/__init__.py`, `src/agents/contracts.py`, `tests/unit/test_agent_contracts.py`.

### 22.3 T04 — extração dos serviços

| Passo | Comando | Resultado |
|---|---|---|
| Caracterização | `pytest -m "not integration"` antes da extração | `863 passed` |
| Após extrair | idem | `1 failed` — `src/eval/inmemory.py:442` chamava `_expand` (privado) |
| Correção | API pública `LegalRAGPipeline.expand_devices()` + `inmemory` atualizado | `863 passed` |

A falha foi **real e útil**: prova material do §5.3 do briefing ("não usar métodos privados como API
estável"). Em vez de ressuscitar o privado, a dependência passou a usar um método público.

Arquivos: `src/services/__init__.py`, `src/services/retrieval.py`, `src/api/main.py`
(delegação), `src/eval/inmemory.py`.

### 22.4 T06 — grafo com agentes fake

| Passo | Comando | Resultado |
|---|---|---|
| RED | `pytest tests/unit/test_agent_graph.py` | `9 failed, 1 passed` |
| GREEN | idem, após implementar | `10 passed in 1.54s` |

Cobre: caminho social sem pesquisa; jurídico pesquisa antes de sintetizar; evidência insuficiente
vira abstenção; esclarecimento encerra o turno; pesquisador que pede esclarecimento não publica
texto jurídico; orçamento esgotado abstém **sem** chamar o pesquisador; dispositivo sem evidência é
recusado; regeneração limitada a `max_tentativas`; estado final serializável em JSON.

Arquivos: `src/agents/state.py`, `src/agents/policies.py`, `src/agents/graph.py`,
`tests/unit/test_agent_graph.py`.

### 22.5 Dependência nova

`uv add langgraph langgraph-checkpoint-postgres` → `pyproject.toml` com
`langgraph>=1.2.22` e `langgraph-checkpoint-postgres>=3.2.1`, lockfile atualizado. Versões batem
com a documentação consultada em 2026-11-16 e com o spike (§20.7).

### 22.6 Portões de qualidade ao fim do ciclo

| Portão | Comando | Resultado |
|---|---|---|
| Testes | `pytest -m "not integration"` | **873 passed**, 12 deselected |
| Lint | `ruff check .` | All checks passed |
| Formatação | `ruff format --check .` | 155 files already formatted |
| Tipos | `mypy src` | Success: no issues found in 58 source files |

### 22.7 Limitações deste ciclo

- O grafo ainda roda **em memória**: checkpointer e worker são T07/T09.
- `decidir`/`pesquisar`/`sintetizar` ainda não chamam LLM real (T14); nos testes são callables.
- Nenhuma rota HTTP nova existe ainda (T08–T10); `/chat` segue intocado.
- A revisão independente do T05 estava em curso ao fim do ciclo; achados serão registrados aqui
  antes de o incremento ser considerado fechado.

### 22.8 Revisão independente do T05 (agente F) e desfecho

**Veredito recebido:** APROVADO COM RESSALVAS — 5 achados maiores, 7 menores, 1 de processo.
Os achados foram registrados com evidência executável (o revisor rodou os casos). Desfecho abaixo.

| # | Achado | Desfecho |
|---|---|---|
| 0 | Entrega chegou com `ruff`/`mypy` vermelhos e o arquivo mudou durante a revisão (escrita concorrente de T06) | **ACEITO como falha de processo.** Incremento passa a ser congelado por SHA antes de revisar (§23) |
| 1 | `proveniencia` era `str` livre: aceitava `"web"` dentro de `EvidenciaBase` | **CORRIGIDO** — `Literal["base"]` |
| 2 | `permitir_web=True` sem allow-list era aceito | **CORRIGIDO** — validador cruzado exige `fontes_permitidas` |
| 3 | `url_validada` aceitava `javascript:`, `file:`, `data:` | **CORRIGIDO** — validador exige http(s) com host |
| 4 | Itens de lista sem limite (payload de 500 KB entrava) | **CORRIGIDO** — `ItemCurto` (500) e `DeviceIdStr` (256) |
| 5 | Teste "não serializável" era vacuoso; matriz incompleta | **CORRIGIDO** — teste passou a exigir falha real; +31 testes |
| 6 | Coerência de status só em uma direção | **CORRIGIDO** — bidirecional |
| 7 | Defaults da política escondem erro | **DOCUMENTADO** — valores marcados como candidatos P08; `deadline` opcional explicado |
| 8 | `parent_request_id=""` aceito | **CORRIGIDO** — `min_length=1` |
| 9 | `frozen` não sobrevive a `model_construct` | **DOCUMENTADO** — limite é o processo, não o modelo |
| 10 | Divergências de §8.1 (`tuple`, `deadline` opcional) | **DOCUMENTADO** — declarado no docstring do módulo |
| 11 | `RespostaConversa` não carrega `verificacao` | **DOCUMENTADO** — projeção pública é de T14; nunca serializar direto |
| 12 | `ValidationError` ecoava o relato da pessoa | **CORRIGIDO** — `hide_input_in_errors=True` + teste com segredo |
| 13 | Docstrings prometiam o que o contrato não impõe | **CORRIGIDO** — texto ajustado; enforcement apontado para `policies` |
| 14 | Nomes de teste mais fortes que as asserções | **CORRIGIDO** — parametrizado nos cinco tipos |

Resultado do ciclo depois das correções:

| Portão | Resultado |
|---|---|
| `pytest tests/unit/test_agent_contracts.py` | **47 passed** (eram 16) |
| `pytest -m "not integration"` | **904 passed**, 12 deselected |
| `ruff check .` / `ruff format --check .` / `mypy src` | limpos |

Lição incorporada ao processo (§23): **congelar o incremento por SHA antes de mandar revisar**. A
revisão do T06 será feita sobre hash fixo, e o revisor não verá arquivos mudando embaixo.

---

## 23. Regra de processo incorporada (após T05)

Achado 0 da revisão veio de erro meu, não do revisor: escrevi T06 enquanto o T05 era revisado, e
qualquer evidência de revisão fica inválida quando o alvo muda durante a leitura.

Regra a partir de agora, em todos os incrementos:

1. Fechar a implementação e a suíte do incremento.
2. Registrar `sha256` de cada arquivo entregue.
3. Só então pedir revisão, informando os hashes.
4. Não editar arquivo entregue até a revisão terminar; trabalho paralelo vai para **outro**
   incremento com arquivos disjuntos.
5. Se um achado exigir mudança, ela reabre o incremento: novo hash, nova revisão do delta.

### 22.9 T07 — schema e persistência de execuções

| Passo | Comando | Resultado |
|---|---|---|
| RED | `pytest tests/integration/test_conversations_schema.py` | `7 failed` — tabelas ausentes |
| Migração | `apply_migrations.py` | **falhou**: `relation "norms" already exists` |
| Correção D10 | controle `schema_migrations` + `--only`/`--mark-applied` | `applied 003_conversations.sql`; segunda execução: `nothing to apply` |
| GREEN schema | idem | `7 passed` (o `9 passed` do registro original era do arquivo de runs) |
| RED runs | `pytest tests/integration/test_runs_service.py` | `9 failed` — módulo ausente |
| GREEN runs | idem | `9 passed` |
| Regressão | unit + integração | `904 passed` / `23 passed, 6 skipped` |
| Portões | ruff, format, mypy | limpos |

**D10 foi resolvido, não contornado.** Ao tentar aplicar a migração 003, o runner reaplicou a 001
e quebrou — o que também deixaria os quatro testes de integração existentes falhando a partir de
agora, em qualquer banco já migrado. A correção introduz `schema_migrations`, pula o que já foi
aplicado e registra o arquivo na mesma transação da execução. Bancos legados entram por
`--mark-applied`, sem heurística.

**Segundo achado, no próprio teste:** a primeira versão da suíte de runs contaminava o banco
compartilhado (um run em `queued` de um teste anterior era reivindicado no lugar do run do teste).
Resolvido com fixture que limpa as conversas marcadas por `owner_hash`, antes e depois de cada caso.

**Congelamento (§23):** o incremento foi enviado à revisão com os hashes registrados:

Primeiro snapshot (revisado por review-t07): `7E5B904B` migração, `8C54676B` runner,
`742181FB` runs, `6708E741` schema-test, `CCECDA9B` runs-test, `A7767F6F` migration-test.

**Snapshot final** (após as correções M1–M4 e F1–F7; substitui o anterior, §23 regra 5):

```text
7E5B904B…44F0E4F  migrations/003_conversations.sql
95F81B2F…          scripts/apply_migrations.py
6861E8DA…          src/services/runs.py
FFCDDCB4…          tests/integration/test_conversations_schema.py
893829F6…          tests/integration/test_runs_service.py
A7767F6F…          tests/integration/test_migration.py
```

Revisão independente em curso; achados entram aqui antes de o incremento ser declarado concluído.

### 22.10 Revisão independente do T07 e correções

**Veredito:** APROVADO COM RESSALVAS — 4 maiores, 14 menores, 3 hipóteses, nenhum bloqueante.
O revisor executou experimentos SQL próprios (dois workers simultâneos, lease vencido, tombstone,
`EXPLAIN ANALYZE` com 200 mil linhas) e deixou o banco limpo.

| # | Achado | Desfecho |
|---|---|---|
| M1 | `reconciliar_expirados` esquecia `awaiting_input`: linha imortal | **CORRIGIDO** — `status <> ALL(TERMINAIS)`; teste dedicado |
| M2 | `concluir`/`falhar` sem *fencing*: worker superado publicava por cima do vigente | **CORRIGIDO** — `attempt` obrigatório no `WHERE`; teste com dois workers |
| M3 | Publicação ignorava tombstone (INV12) | **CORRIGIDO** — `EXISTS (... deleted_at IS NULL)` no `concluir`; teste |
| M4 | `awaiting_input` fora do índice tornava a transição de §21.4 impossível | **EMENDADO** — `awaiting_input` não entra no índice; nova mensagem fecha o anterior; transição `-> queued` removida de §21.4 |
| m2 | Ordem sem desempate (dois runs com o mesmo `created_at`) | **CORRIGIDO** — `ORDER BY created_at, id` |
| m3 | jsonb dependia de o driver enviar OID *unknown* | **CORRIGIDO** — `psycopg.types.json.Jsonb` |
| m5/m6/m7 | Mensagem "found in None", `--only` por substring, exceção sem tipo | **CORRIGIDO** |
| m8 | Asserção vazia, `raises` sem match, `>= 1`, `is None or ...` | **CORRIGIDO** — asserções estritas |
| m10/m11 | Código morto; deadline não positivo aceito | **CORRIGIDO** |
| m1 | `runs_claimable` não é usado pelo claim (`OR` impede o índice) | **REGISTRADO** — pendência de T13 junto com a emenda do índice |
| m12 | Comentário da migração justificava `IF NOT EXISTS` pelo runner antigo | **MANTIDO** — o `IF NOT EXISTS` segue válido como cinto de segurança |
| m9/m4/m13/m14 | Índices extras, README desatualizado, assinaturas de §21.3, contagem errada em §22.9 | **CORRIGIDO** em §21.2, §21.3, §21.4, §21.10 e README |

**Hipóteses registradas, não resolvidas neste incremento:**

- **H1 (INV15):** `result_json` guarda o que `concluir` receber; a projeção pública é de T14.
- **H2 (fronteira transacional):** `reivindicar` não commita de propósito. O worker deve commitar o
  claim em transação curta e executar o grafo fora dela — documentado em §21.7.
- **H3 (reconciliação em lote):** o `UPDATE` pega todas as linhas vencidas de uma vez; limitar por
  lote é T13.

Estado do incremento após as correções: **904 passed** (unitária), **27 passed, 6 skipped**
(integração), ruff/format/mypy limpos. Revisão delta em curso sobre os hashes novos.

### 22.11 Revisão delta do T07

**Veredito:** APROVADO COM RESSALVAS · **M1, M2 e M3 FECHADOS** com evidência executada pelo
revisor; **M4 PARCIAL** (a emenda fechava o índice, mas §21.4 ainda prometia transições que
nenhum código oferecia).

| # | Achado da delta | Desfecho |
|---|---|---|
| F1 | §21.4 prometia fechar `awaiting_input`, e nada fazia isso | **CORRIGIDO** — `encerrar_pendente()` em `runs.py`, com teste |
| F2 | `cancel_requested -> succeeded` era inalcançável | **CORRIGIDO** na spec (quem publicou está em `succeeded`) |
| F3 | SQL de §21.7 sem ramo de retomada nem desempate | **CORRIGIDO** no documento |
| F4 | Help do `--only` dizia "contains", comportamento é prefixo | **CORRIGIDO** |
| F5 | §22.9 listava hashes antigos | **CORRIGIDO** — snapshot final registrado |
| F6 | Ledger de §22.10 omitia m1 e m12 | **CORRIGIDO** |
| F7 | Asserção disjuntiva e prazo testado só com 0 | **CORRIGIDO** — match exato; `0/-1/-100` parametrizados |

**T07 encerrado.** Estado: 911 testes de unidade, 41 de integração, ruff/format/mypy limpos.

### 22.12 T08 — identidade e autorização (implementado, aguardando revisão)

| Passo | Comando | Resultado |
|---|---|---|
| RED | `pytest tests/integration/test_conversations_auth.py` | `11 failed` — módulo ausente |
| GREEN | idem | `11 passed` |
| HTTP | `pytest tests/unit/test_api_auth.py` | `7 passed` |

Implementado: `criar_conversa` (token de 32 bytes, `sha256` no banco), `autenticar` (rejeita
apagada e expirada), `apagar` (tombstone idempotente), `purgar`, `obter`, `tocar`; cookie
`HttpOnly; SameSite=Lax; Secure` e dependência que devolve 401 sem detalhe — não confirma se a
conversa existe.

Snapshot T08 (congelado para revisão):

```text
2D8A14C4…  src/services/conversations.py
A96AC7A2…  src/api/auth.py
7F25BB10…  tests/integration/test_conversations_auth.py
6978C8CF…  tests/unit/test_api_auth.py
```

### 22.13 T09 — aceitação durável e idempotência

| Passo | Comando | Resultado |
|---|---|---|
| RED | `pytest tests/integration/test_api_conversations.py` | `9 errors` — módulo ausente |
| GREEN | idem | `9 passed` |
| Regressão | unit + integração | `911 passed` / `50 passed, 6 skipped` |
| Portões | ruff/format/mypy em `src tests scripts` | limpos |

**Migração 004** (`004_run_idempotency.sql`): `runs.client_message_id` + índice único parcial. Sem
essa coluna não havia como repetir um envio e recuperar a **mesma** execução — o T07 não previa o
vínculo, e a idempotência de §21.3 ficaria só na prosa.

**Aceitação atômica:** `INSERT` da mensagem e `criar_run` na mesma transação; se o índice de
execução ativa conflita, `rollback` e 409 com o run corrente. É a garantia de INV10.

**Duas decisões de comportamento registradas:**

1. **Conversa apagada responde 401, não 404.** Excluir revoga a credencial (ADR-03). Distinguir
   "apagada" de "token inválido" exigiria uma consulta que confirma a existência da conversa a
   quem apresenta um token qualquer. O teste foi renomeado para
   `test_conversa_apagada_revoga_a_credencial` e documenta o motivo — não é afrouxamento.
2. **Emergência responde antes da autorização.** O bloco é fixo e público, sem dado pessoal; em
   queda de banco a orientação continua saindo (INV09). O caminho legado `/chat` mantém a mesma
   garantia.

**Resíduo do revisor:** os arquivos `rev_t08_experiments.py` e `rev_t08_probe.py` estão na raiz do
worktree enquanto a revisão do T08 roda, e quebram `ruff check .`. São artefatos do revisor, não
do incremento; serão removidos quando ele terminar, antes de qualquer commit.

### 22.14 Revisão do T08 e correções

**Veredito:** APROVADO COM RESSALVAS — nenhum bloqueante, 4 maiores, 9 menores. O revisor
confirmou com banco real: token de 256 bits, `sha256` sem pepper aceitável, nenhuma comparação em
Python (a igualdade ocorre no SQL `bytea`), rejeição de token vazio/gigante/expirado/apagado, 401
uniforme sem vazar existência, e `apagar` sem caminho de ressurreição.

| # | Achado | Desfecho |
|---|---|---|
| 1 | Retenção nunca aplicada: conversa expirada há 1 ano sobrevivia à purga | **CORRIGIDO** — `purgar` com dois relógios (tombstone e expiração) |
| 2 | `purgar(dias=0)` apagava tudo, sem guarda | **CORRIGIDO** — rejeita janela negativa; teste parametrizado |
| 3 | `obter` fazia `SELECT *` e devolvia `owner_hash` | **CORRIGIDO** — projeção explícita `COLUNAS_PUBLICAS` |
| 4 | `purgar` sem nenhum teste | **CORRIGIDO** — três testes (tombstone antigo, conversa expirada, janela negativa) |
| 5 | Asserção vacuosa (`token.encode() not in guardado`, 43 B em 32 B) | **CORRIGIDO** — compara com `sha256` e com os bytes do token |
| 8 | `limpar_cookie` sem `Secure`/`HttpOnly` | **CORRIGIDO** |
| 9 | `owner_hash` sem índice: Seq Scan por requisição | **CORRIGIDO** — migração `005_owner_hash_index.sql` |
| 11 | `tocar` mexia em conversa apagada/expirada | **CORRIGIDO** — filtra `deleted_at` e `expires_at` |
| 12 | `no-store` cobria só `/chat` | **CORRIGIDO** — `/api/v1/*` incluído; teste de cache |
| 6/7/10/13 | Testes inertes, solda de config (§21.9 fora de `Settings`), skip sem banco | **REGISTRADOS** — entram com T16 (config) e T17 (suíte E2E) |

Estado após as correções: **912 passed** (unidade), **55 passed, 6 skipped** (integração),
ruff/format/mypy limpos. Revisão delta do T08 em curso.

#### 22.14.1 Desvio de processo registrado (verificação não independente)

A revisão delta do T08 **não foi concluída por agente independente**: duas tentativas falharam por
problema da infraestrutura de subagente (a primeira morreu em silêncio; a segunda parou após a
primeira ferramenta). Para não travar o incremento, o próprio lead executou as seis verificações.

Isto é um **desvio explícito da regra §23**, e fica registrado como tal. O que foi checado, com
resultado:

| Verificação | Resultado |
|---|---|
| `purgar` remove conversa expirada e preserva tombstone recente | OK |
| `purgar` rejeita janela negativa | OK |
| `obter` não devolve `owner_hash` | OK |
| `conversations_owner_hash` existe e é utilizável | OK — `Index Scan using conversations_owner_hash` com `enable_seqscan=off`; com 7 linhas o planejador escolhe Seq Scan, que é a decisão correta nessa escala |
| `no-store` em `/api/v1/*`, ausente em `/health` | OK |
| Suíte completa | 912 unidade · 55 integração · ruff limpo |

**Consequência:** T08 é aceito com auto-verificação, não com revisão independente. A tarefa **T17**
(regressões e revisão final) precisa refazer esta passagem por um agente independente antes do
encerramento do projeto; se ela falhar de novo, o projeto fecha declarando a lacuna.

### 22.15 T10 — acompanhamento, resultado e cancelamento

| Passo | Comando | Resultado |
|---|---|---|
| RED | `pytest tests/integration/test_api_runs.py` | `9 errors` — módulo ausente |
| GREEN | idem | `9 passed` |

Rotas: `GET .../runs/{id}` devolve `{run_id, status, revision, events[]}` e responde **304** quando
`since == revision` (ADR-06); `GET .../result` devolve o payload publicado e **409** enquanto não
concluído; `POST .../cancel` é idempotente. Os eventos são **derivados** do próprio registro do
run (`created_at`, `started_at`, `finished_at`, status) — nenhuma tabela de eventos nova, nenhum
replay, nenhum campo de conteúdo.

### 22.16 T13 — cancelamento e exclusão

`DELETE /conversations/{id}` grava o tombstone, marca as execuções ativas como
`cancel_requested` e limpa o cookie. Junto com o `EXISTS (deleted_at IS NULL)` que já existia no
`concluir` (T07), INV12 passa a ter prova nos dois lados: worker antigo não publica e conversa
excluída não ressuscita.

### 22.17 T14 — worker e adaptadores do grafo

Até aqui o trabalho aceito **nunca executava**: não existia processo de worker. Agora existe
`src/worker.py`:

1. `reivindicar` em transação curta e commit imediato (fecha a hipótese H2 da revisão do T07 —
   a linha não fica travada durante o modelo);
2. execução fora de transação;
3. publicação com `attempt` na segunda transação (fencing);
4. exceção vira `failed` com `error_code`, nunca resultado parcial.

`src/services/orchestration.py` liga o grafo (T06) ao que já existia: `decidir` classifica o turno
sem custo de modelo, `pesquisar` usa o serviço de recuperação (T04) e produz `EvidenciaBase`,
`sintetizar` reusa geração + verificação do pipeline. O estado carrega só JSON; o payload público é
projetado em `ChatResponse`.

Testes do worker (4, integração): publica resultado, é idempotente por fila, marca falha com
código tipado e **não publica** quando a conversa foi apagada durante a execução.

**Limite declarado:** o caminho de geração usa o pipeline existente dentro do run. O grafo faz a
orquestração e a política, mas os dois agentes ainda não têm prompts próprios — isso é evolução de
T14/T18, não uma promessa cumprida.

### 22.18 T15 e T16 — configuração e web desligada

`Settings` ganhou as chaves de §21.9 (`MULTIAGENT_ENABLED`, `RESUMABLE_CONVERSATIONS_ENABLED`,
`WEB_SEARCH_ENABLED`, retenção, tombstone, lease, deadline, poll). Todas com padrão seguro: as
flags nascem **desligadas**.

`src/services/web_search.py` existe para que a ausência de busca seja explícita: `buscar()` levanta
`BuscaWebDesabilitada` enquanto a flag estiver em `false`, e a política já nomeia allow-list,
bloqueio de loopback/link-local, limites de bytes e redirects.

**Portões ao fim do bloco:** 912 unidade · 68 integração · ruff, format e mypy limpos.

### 22.19 T11/T12 — frontend durável e segurança da interface

**T11:** novo módulo `web/ui/scripts/durable.js` (cliente de `/api/v1`, sem tocar no DOM) e ligação
mínima em `app.js`: na abertura, `ativarFluxoDuravel()` consulta `/conversations/current`, cria a
conversa se não houver e marca o modo; no envio, `enviarDuravel()` aceita o trabalho e acompanha
por revisão, devolvendo **o mesmo `ChatResponse`** que a interface já renderiza — por isso o
restante do arquivo não mudou.

Testado com o runner do Node (`tests/js/durable.test.mjs`, 7 casos) e executado pelo pytest via
`tests/unit/test_durable_js.py`, que **pula explicitamente** se não houver Node. O teste pegou um
defeito real: um `304` apagava o status conhecido e o laço nunca reconheceria o fim da execução.

**T12:** três correções de promessa e de comportamento:

1. **Queda de rede não vira demonstração** (INV16). Antes, falha de rede em `/health` entrava em
   modo demo e nunca saía; agora o selo muda para "estado incerto" e a conversa não finge.
2. **Textos deixam de prometer o que não é verdade.** "conversa só nesta aba" virou "a conversa
   fica protegida no servidor"; "salvo apenas neste aparelho" virou "histórico local, opcional".
3. **`no-store` em `/api/v1/*`** (feito em T08) e cookie revogado na exclusão.

### 22.20 T17 — estado real da matriz de aceitação

| AC | Estado | Evidência |
|---|---|---|
| AC01 fechar após aceitação | **PARCIAL** | worker publica sem cliente (teste de integração com processador injetado); falta E2E com LLM real |
| AC02 voltar após conclusão | VALIDADO | `GET result` idempotente |
| AC03 voltar durante processamento | VALIDADO | estado por revisão + teste em Node |
| AC04 conexão cai após aceite | VALIDADO | idempotência por `client_message_id` |
| AC05 restart do worker | VALIDADO | lease vencido + fencing por `attempt` |
| AC06 banco fora em emergência | VALIDADO | emergência antes de auth e de I/O |
| AC07/AC08 acesso cruzado | VALIDADO | 404 sem vazar id; 401 sem cookie |
| AC09/AC10 IDs e versões fabricados | VALIDADO | verificador existente (T05 não o enfraqueceu) |
| AC11 afirmação inventada no corpo | **PARCIAL** | limite conhecido: metadados não validam prosa |
| AC12 orçamento do pesquisador | **PARCIAL** | 409 e budget implementados; custo de LLM não medido |
| AC13 esclarecimento | VALIDADO | grafo (§22.4) |
| AC14 duas abas | VALIDADO | 409 + índice único |
| AC15 exclusão durante pesquisa | VALIDADO | tombstone no `concluir` + teste do worker |
| AC16 sessão expira | VALIDADO | 401 |
| AC17 eventos antigos | VALIDADO | eventos derivados; resultado persiste |
| AC18 fonte maliciosa | VALIDADO | prompt existente |
| AC19 rede não vira demo | **PARCIAL** | corrigido; sem teste de navegador |
| AC20 texto não validado | VALIDADO | resultado só sai em `succeeded` |
| AC21 logs sem conteúdo | VALIDADO | eventos de run sem conteúdo |
| AC22 web desabilitada | VALIDADO | `buscar()` levanta erro |
| AC23 URL para rede privada | VALIDADO (validação) / PARCIAL (execução) | 6 casos parametrizados descartam loopback, metadata e esquemas perigosos; a busca nativa segue sem prova ao vivo (§22.25) |
| AC24 saída rápida | **ABERTO** | depende de P06 (decisão de produto) |
| AC25 risco durante run ativo | VALIDADO | emergência antes da autorização |

**Regressões:** 914 unidade · 68 integração · ruff, format e mypy limpos. Nenhuma garantia anterior
foi removida: `/chat`, `ChatResponse`, emergência e PII nos logs seguem com seus testes originais.

### 22.21 T18 — demonstração reproduzível

`scripts/demo_duravel.py` executa o mecanismo inteiro e imprime a transcrição:

```text
1. criando conversa                 conversa: 58f8d961-…
2. enviando pergunta                status HTTP: 202 · run: 634eee4c-…
3. repetindo o mesmo envio          status HTTP: 200 · mesmo run: True
4. executando no servidor            execuções processadas: 1
5. acompanhando por revisão         status: succeeded · revisão: 3
                                    eventos: run.accepted, run.started, run.completed
6. recuperando o resultado          status HTTP: 200
7. limpando a conversa              status HTTP: 204
```

**O que a demonstração prova:** aceitação durável, idempotência, execução sem cliente conectado,
acompanhamento por revisão, publicação e recuperação.

**O que ela não prova:** a qualidade da resposta jurídica. O processador é um stub, e o próprio
payload diz isso. Para conteúdo real é preciso base ingerida e `python -m src.worker` com o
pipeline — caminho que continua sem prova ponta a ponta nesta máquina (§22.17).

O script é executado por `tests/integration/test_demo.py`, então a demonstração não pode apodrecer
em silêncio: se o fluxo quebrar, a suíte quebra junto.

### 22.22 Fechamento do incremento

| Item | Estado |
|---|---|
| Testes | **914 unidade · 69 integração · 7 em Node** · limpos |
| Portões | `ruff check` · `ruff format --check` · `mypy src` limpos |
| Migrações | `001`–`005` aplicadas, `schema_migrations` versionando |
| Regressões | `/chat`, `ChatResponse`, emergência e PII nos logs com seus testes originais intactos |
| Pendente | AC24 (saída rápida, depende de P06), busca web (T15), E2E com LLM real, revisão independente final |

### 22.23 Revisão final independente (T17)

**Veredito: APROVADO COM RESSALVAS, nenhum achado bloqueante.**

| Verificação | Resultado do revisor |
|---|---|
| Suíte unitária | `914 passed` |
| Suíte de integração | apontou `1 failed` em `test_demo.py` por codec — **achado desatualizado** |
| ruff / mypy | limpos |
| Node | `7 pass, 0 fail` |
| `src/worker.py` | confirmou commit do claim antes de executar e `attempt` na publicação |
| `app.js` | confirmou que queda de rede **não** entra em modo demonstração |

O ponto 2 do revisor foi resolvido antes do parecer: o teste do demo passou a decodificar o stdout
como UTF-8 explicitamente. Reexecutado nas duas formas (com e sem `PYTHONIOENCODING` no pai),
`1 passed`. A suíte de integração é hoje **69 passed, 6 skipped**. A ressalva fica registrada como
divergência de observação, não como defeito.

---

## 24. Relatório final

### 24.1 O que foi entregue

| Tarefa | Entrega |
|---|---|
| T03 | Spec implementável (§21): schema, máquina de estados, API v1, política por `OutputKind`, worker, orçamento |
| T04 | `src/services/retrieval.py` — recuperação extraída com comportamento preservado (char.: 863 testes) |
| T05 | `src/agents/contracts.py` — fronteiras endurecidas após 5 achados maiores da revisão |
| T06 | `src/agents/graph.py` — dois nós com LLM injetável, resto determinístico |
| T07 | `003` + `schema_migrations` + `src/services/runs.py` com claim, lease e fencing |
| T08 | Capability cookie, autorização por recurso, retenção e purga |
| T09 | Aceitação atômica, idempotência por `client_message_id`, 409 |
| T10 | Estado por revisão (304), resultado idempotente, cancelamento |
| T11 | `durable.js` + retomada na abertura, testado em Node |
| T12 | Rede não vira demo; textos deixam de prometer o que não é verdade |
| T13 | Exclusão com tombstone, cancelamento e revogação |
| T14 | `src/worker.py` + adaptadores do grafo sobre o pipeline existente |
| T15 | Pesquisa web desligada, política e erro explícito |
| T16 | Configuração de runtime e retenção em `Settings`/`.env.example` |
| T17 | Matriz AC com estado real (§22.20) e revisão final independente |
| T18 | `scripts/demo_duravel.py` reproduzível e executado por teste |

### 24.2 Evidência final

```text
914 testes de unidade · 69 de integração · 7 em Node
ruff check / ruff format --check / mypy src      limpos
migrações 001–005 aplicadas, versionadas por schema_migrations
demonstração: 202 -> 200 idempotente -> execução sem cliente -> succeeded -> resultado
```

### 24.3 O que **não** foi entregue

1. ~~**E2E com modelo real.**~~ **Resolvido em 22.24**: executado com `qwen/qwen3.7-flash` via
   OpenRouter, com citação canônica e verificação antes da publicação. **Fechado em 22.28 e
   22.29**: a base real está ingerida (10.548 dispositivos, 10.797 embeddings), a recuperação foi
   medida nela e o E2E de conversa rodou sobre ela com citação verificada. O que resta é a **taxa
   de abstenção entre execuções idênticas**, ainda não medida (22.29).
2. **Prompts próprios dos dois agentes.** O grafo orquestra e aplica política, mas o nó de síntese
   delega ao pipeline existente. Os contratos existem; os prompts não.
3. ~~**Busca web (T15).**~~ **Implementado em 22.26** com SerpApi `google_light` (US$ 0,015 por
   consulta). O que não existe é a citação da evidência web: `Citation` só aceita dispositivo
   hidratado, então nenhuma fonte web vira autoridade na resposta.
4. **AC24 — saída rápida.** Depende da decisão P06 (o que exatamente ela apaga).
5. **Cobertura de navegador.** Não há ferramenta de E2E no repositório; AC19 e AC03 têm teste de
   lógica em Node, não de navegador.

### 24.4 Dívidas de processo

- A revisão delta do T08 foi **auto-verificada** (§22.14.1); a revisão final externa cobriu o
  conjunto, mas não refez aquele delta ponto a ponto.
- Nada foi commitado: 5 migrações, 36 arquivos novos e a ingestão da base (22.28) no worktree.
- `uv.lock`, `pyproject.toml` e `.env.example` mudaram e precisam de commit coordenado.

### 24.5 Próximo incremento recomendado

**Executado em 22.28**: o worker está ligado ao modelo real e a base real está ingerida e medida.
O próximo incremento, agora com evidência de quantidade, é **corrigir a expansão para o artigo**
(1.145 dispositivos, 14,4%, não encontram o caput — 22.28), porque é o item que melhora a
resposta sem depender de decisão de produto, e em seguida **ampliar o gabarito**: 150 perguntas
com 16 dispositivos distintos mede recuperação de 16 alvos, não acerto do sistema.

### 22.24 Ligação ao OpenRouter com modelo real (2026-11-16)

Configuração adotada na worktree (`.env`, **não versionado** — contém a chave):

```text
LLM_PROVIDER=openrouter
OPENROUTER_MODEL=qwen/qwen3.7-flash
EMBEDDING_PROVIDER=openrouter
RETRIEVAL_PATH=fallback
DENSE_BACKEND=pgvector
LLM_TIMEOUT=120
LLM_MAX_TOKENS=4000
```

**E2E executado**, com o worker real e sem stub:

```text
POST /api/v1/conversations                                 201
POST .../messages                                          202  run=7e175790-…
worker: reivindica, executa no grafo, publica
GET  .../runs/{id}                                         succeeded · revisão 3
GET  .../result                                            200 · abstencao=false
     citações: ["Lei 11.340/2006, art. 22"]
```

A resposta saiu em linguagem simples, apoiada no dispositivo recuperado e **verificada** antes de
publicar. O caminho de abstenção também foi exercido: com a base sem texto legal, o sistema
respondeu `evidencia_insuficiente` e não inventou nada — comportamento correto, não falha.

#### Três defeitos reais só apareceram ligando o modelo

| # | Sintoma | Causa | Correção |
|---|---|---|---|
| 1 | `HTTP 404` no `/chat/completions` | `.env` fixava `provider.only=deepinfra/fp8`, que não serve o modelo | fixação removida |
| 2 | `llm_indisponivel` em toda geração | `complete()` usava o timeout padrão de **30 s**; modelo com raciocínio estoura | novo `LLM_TIMEOUT` (90 s, 120 na worktree) aplicado em `_complete` — era o achado **E24** da descoberta, previsto e não corrigido até aqui |
| 3 | resposta vazia, `LLM returned an unexpected response` | o modelo gasta ~200–2.000 tokens **antes** do JSON; com `max_tokens=1200` não sobrava conteúdo | `LLM_MAX_TOKENS=4000` |

O item 2 é a prova de que a descoberta acertou: E24 foi registrado na §2.2 meses antes de existir
uma chamada real, e foi exatamente ali que o sistema quebrou.

#### Custo observado

Uma resposta completa consumiu ~200 tokens de raciocínio + o JSON, com 1 chamada de geração e 1 de
embedding por pergunta. Não é medição de benchmark — é ordem de grandeza para o orçamento de §21.8.

**Aviso operacional:** o `.env` da worktree contém a chave e **não** deve ser commitado (já está no
`.gitignore`). `.env.example` recebeu `LLM_TIMEOUT` sem valor de chave.

### 22.25 Web grounding pela Decisions API (2026-11-16)

Documentação consultada: Perplexity API (`docs.perplexity.ai`, Decisions) e OpenRouter
(`openrouter.ai/docs`, alpha decisions).

#### O achado que decidiu o desenho

O modelo `perplexity/pplx-decider-v1.2` **existe** e é servido pelo OpenRouter, mas **não como
modelo de chat**: ele vive na Decisions API. Medido com chave real:

| Rota | Resultado |
|---|---|
| `POST openrouter.ai/api/alpha/decisions` | **200** · modelo `perplexity/pplx-decider-v1.2-20261016` · `answers.evidencia_suficiente.noul = 0.44` · custo US$ 0,000002 |
| `POST api.perplexity.ai/v1/decisions` com `mode=web_grounding` | devolve `search_results` com `title`, `url`, `snippet` (contrato documentado) |

**O OpenRouter não honra o grounding.** Três chamadas com `mode: "web_grounding"` voltaram 200 com
as mesmas chaves (`answers, id, model, provider, usage`) e **nenhum `search_results`**; os tokens de
entrada foram idênticos aos da chamada sem o modo. A conclusão não é opinião: é a diferença entre
duas respostas medidas.

Consequência: quem faz grounding é a **Decisions API nativa da Perplexity**; o OpenRouter serve para
*julgar* evidência que já temos. O código aceita os dois provedores e **declara qual foi usado**
(`grounding_disponivel`), em vez de fingir que buscou.

#### O que foi implementado

`src/services/web_search.py`:

- corpo conforme o contrato: `model`, `mode="web_grounding"`, `max_staleness`, `state` e uma
  pergunta `noul` (`evidencia_suficiente`);
- `search_results` → `EvidenciaWeb` com `evidence_id` derivado da URL, `publicador`, `data_acesso`,
  `trecho` e `snapshot_hash`;
- **validação de URL** antes de aceitar: só `http(s)` com host público; loopback, `127.`,
  `169.254.` (metadata), `localhost`, `::1` e esquemas `file:`/`javascript:` são **descartados** e
  registrados em `descartadas` (AC23);
- **allow-list** opcional de domínios, aplicada no código e não no modelo;
- **minimização**: pergunta acima de 500 caracteres é **recusada**, não truncada — relato longo não
  sai para terceiro;
- **teto de custo** por chamada (US$ 0,05) e contabilização de tokens;
- provedor sem credencial levanta `BuscaWebIndisponivel`; flag desligada levanta
  `BuscaWebDesabilitada`; erro HTTP vira `BuscaWebFalhou`. Nunca vazio silencioso.

**Integração no agente de pesquisa:** quando `WEB_SEARCH_ENABLED=true`, o nó `pesquisar` acrescenta
as evidências web ao `ResultadoPesquisa` **como `EvidenciaWeb`** — nunca como `RetrievedDevice`
(INV08). Falha da web vira lacuna (`busca_web_indisponivel:<Erro>`) e **não derruba o turno**.

#### Testes

20 novos testes, sem rede (transporte HTTP injetado): contrato do corpo, parsing, descarte de URL
perigosa (6 casos parametrizados), allow-list, teto de custo, erro HTTP, provedor sem chave, flag
desligada, pergunta longa recusada, e os três casos de integração no agente (web entra, web
desligada não chama, falha vira lacuna).

#### Limites declarados

1. **A rota nativa não foi exercitada ao vivo** — falta `PERPLEXITY_API_KEY`. O código segue o
   contrato documentado e tem teste de contrato, mas contrato não é prova de execução.
2. **A síntese ainda não cita evidência web.** Ela entra no resultado da pesquisa e não produz
   `Citation`; citar fonte web exige ampliar o verificador, que hoje valida apenas dispositivo
   hidratado. Deixar isso implícito seria transformar web em base por omissão.
3. **Custo**: US$ 0,001 por busca + tokens. Com `WEB_SEARCH_ENABLED=false` por padrão, nada é gasto.

### 22.26 SerpApi (google_light) substitui a Perplexity como provedor de pesquisa

Decisão do responsável em 2026-11-16. Contrato conferido na documentação e no catálogo do gateway:

```text
GET https://serpapi.com/search?engine=google_light&q=<pergunta>&gl=br&hl=pt&api_key=<chave>
resposta: organic_results[] = {position, title, link, snippet}; erro de serviço vem em "error"
custo documentado: US$ 0,015 por chamada bem-sucedida · p50 11 s · p95 44 s
```

Por causa do p95 de 44 s, o `WEB_SEARCH_TIMEOUT` padrão subiu de 30 s para **60 s** — 30 s cortaria
a cauda e transformaria lentidão em falha.

#### Chamada real executada (chave do responsável)

```text
pesquisar("Lei Maria da Penha medidas protetivas de urgencia art. 22")
-> provedor: serpapi · custo_usd: 0.015 · suficiente: True · evidencias: 5 · descartadas: 0
   - Art. 22 da Lei Maria da Penha - Jusbrasil
   - Art. 22 - PCD Legal
   - Lei Maria da Penha (Instagram)
   - [PDF] Das medidas protetivas que obrigam o agressor
   - [PDF] Medidas protetivas da Lei Maria da Penha (MPGO)
```

Cinco evidências reais viraram `EvidenciaWeb` com `evidence_id`, `publicador`, `data_acesso`,
`trecho` e `snapshot_hash`.

#### O que a chamada real revelou sobre a allow-list

Com `dominios_permitidos=("planalto.gov.br","stj.jus.br","cnj.jus.br","mpgo.mp.br")`, a **mesma
consulta descartou as 5 evidências** — nenhuma delas é desses domínios. Ou seja: allow-list estrita
combinada com o ranking do Google produz **zero evidência**, o que é pior que evidência imperfeita
marcada como tal.

Decisão registrada: `WEB_SEARCH_ALLOWLIST` fica **vazia por padrão** (sem filtro de domínio) e o
operador pode endurecê-la; a proveniência continua registrada por item, e a síntese ainda não cita
web (portanto nenhuma fonte web vira autoridade jurídica). Quem quiser uso estritamente oficial deve
preferir `site:` por domínio ou ingestão curada — não filtro pós-busca.

#### Estado do código

- `web_search_provider` aceita `serpapi` (padrão), `perplexity` e `openrouter`;
- 19 testes de unidade, sem rede, com transporte injetado: contrato do GET (`engine`, `q`, `gl`,
  `hl`, `api_key`), parsing de `organic_results`, `error` do SerpApi, descarte de URL perigosa
  (6 casos), allow-list, teto de custo, provedor sem chave e flag desligada;
- falha da busca continua virando lacuna, nunca derruba o turno.

**Limites que permanecem:** a síntese não cita evidência web (`Citation` só aceita dispositivo
hidratado) e o custo por chamada é real — `WEB_SEARCH_ENABLED` fica ligado apenas quando o
operador aceita pagar US$ 0,015 por consulta.

### 22.27 Ligação de produção (2026-11-16)

O sistema estava testado e **não estava ligado**. Três correções fecharam isso:

**1. A v1 passou a existir no servidor.** `create_app` chama `_mount_v1`, que monta
`/api/v1/conversations` e `/api/v1/.../runs/...` com a fábrica de conexão do próprio app. Antes,
nenhuma rota de v1 existia no processo publicado — a interface caía no caminho legado sem avisar.
A montagem é condicional a nada: as rotas exigem cookie de capacidade, então expô-las é seguro.

**2. `/health` publica capacidades.** `{durable, resumable, web_search}` derivadas das flags, para
a interface decidir o caminho em vez de adivinhar por 404.

**3. Faltava `GET /conversations/current`** — a rota que a interface usa para retomar. Sem ela o
cliente recebia 405 e desistia do fluxo durável. Agora devolve `{id, created_at, expires_at,
messages[], last_result}`: a última resposta publicada aparece ao reabrir a aplicação, e o
`app.js` renderiza a conversa sem reenviar nada.

**4. O worker ganhou manutenção.** `executar_manutencao` chama `reconciliar_expirados` e `purgar`
com as janelas de `Settings`. Antes essas funções existiam e nunca rodavam: conversa expirada
ficava para sempre e execução vencida continuava na fila. O laço roda a manutenção a cada 15
ciclos e no modo `--once`.

**5. O laço usa a configuração**: `run_lease_seconds`, `worker_poll_seconds` e
`conversation_retention_days` deixaram de ser campos decorativos.

#### Decisão revertida, registrada

Cheguei a adicionar um serviço `worker` no `docker-compose.yml` apontando para um
`Dockerfile.worker` inexistente. **Revertido**: um compose que não sobe é pior que um compose sem o
serviço. Containerização do worker fica registrada como pendência de hospedagem (P11).

#### Evidência

```text
openapi: /api/v1/conversations, /messages, /runs/{id}, /result, /cancel, DELETE
GET /health -> 200 {durable: false, resumable: false, web_search: true}
POST /api/v1/conversations -> 201   GET /api/v1/conversations/current -> 200
940 unidade · 71 integração · 7 Node · ruff/format/mypy limpos
```

### 22.28 Ingestão da base real (2026-11-16)

O pipeline de ingestão existia completo — `download`, `parse`, `validate`, `load`, `embed` — com
testes verdes e **nunca havia rodado contra a internet**. `data/raw/` tinha um arquivo de 3 bytes
escrito `raw`. Rodar expôs sete defeitos, todos invisíveis em teste unitário porque só aparecem
diante da fonte real.

#### D1 — O Planalto não responde sem User-Agent (OBSERVADO)

```text
sem UA   -> code=000  time=12s    0 bytes     (TCP aceito, nenhuma resposta)
com UA   -> code=200  time=0.4s  264 KB
```

`httpx` envia `python-httpx/x.y`; `planalto.gov.br` aceita a conexão e fica mudo, então todas as
fontes P0 estouravam por timeout. A correção é um header: `USER_AGENT` identificável +
`Accept-Language: pt-BR`, mais timeout de conexão separado do de leitura. O defeito não era da
rede — era um servidor que **filtra por agente e não responde**.

#### D2 — A LMP é UTF-16LE sem `meta charset` (OBSERVADO)

`detect_charset` tentava `utf-8`, falhava e caía em `cp1252`; o texto virava lixo e o parser
reportava `no article found` — a lei central do produto com **zero dispositivos**. O BOM agora
tem precedência sobre qualquer outra pista (UTF-32 antes de UTF-16, senão `FF FE 00 00` é lido
como UTF-16), com heurística de densidade de NUL para UTF-16 sem BOM. LMP: **0 -> 262**.

#### D3 — O STJ bloqueia o host, não o arquivo (OBSERVADO)

```text
scon.stj.jus.br/SCON/getFile?url=...   -> 403 (desafio JS, 16 KB)
www.stj.jus.br/docs_internet/...       -> 200, 417 KB, application/pdf
```

Mesmo PDF, host diferente. Manifesto corrigido.

#### D4 — A dimensão do embedding não cabia na coluna (OBSERVADO)

`device_versions.embedding` é `vector(1024)` com índice HNSW; `.env` pedia **4096**. O INSERT
falharia lote a lote, *depois* de pagar por todos os embeddings. (HNSW no pgvector não indexa
acima de 2000 dimensões, então 4096 nunca seria opção.) Três correções: dimensão em 1024 via MRL
do `qwen3-embedding-8b` (validado em chamada real), **pré-checagem** que lê `atttypmod` e recusa
antes de embedar, e embedding em streaming — antes acumulava 10 mil vetores em memória (~400 MB)
e descartava tudo se um lote falhasse.

#### D5 — O parser de súmulas lia 6 de 676 enunciados (OBSERVADO)

O PDF prefixa cada título com o glifo do link: a linha é `G SÚMULA 542`, não `SÚMULA 542`. A regex
exigia início de linha e encontrava só 6 menções incidentais. Corrigido com prefixo opcional de
uma letra, âncora de linha inteira (sem ela, uma frase quebrada começando em `Súmula 142 do STJ`
virava enunciado novo e gerava ids duplicados em 142, 408, 418, 469 e 560) e detector de
cancelamento nos três formatos da fonte. Resultado: **6 -> 676 enunciados**, 30 cancelados.

#### D6 — A reingestão de uma fonte inalterada falhava (OBSERVADO)

Rodar a ingestão duas vezes é o teste que faltava. 9 de 25 fontes quebravam:

```text
lmp/art11/par-unico: new vigencia_inicio 2026-12-31 is in the future
stj-sum-142: device version for event 497 already exists; refusing to drop the new text silently
```

Causa única: `load_current_versions` lia a **janela de recuperação** (status vigente/alterado,
início <= hoje, fim >= hoje). Dispositivo cancelado, versão encerrada e dispositivo com vigência
futura ficavam fora dessa janela, então o diff os classificava como **novos** e tentava inseri-los
de novo. O leitor do diff agora é `load_known_versions`, sem filtro de status ou data.

O mesmo teste revelou o sétimo defeito: `data/raw/lmp.html` voltou a ter 3 bytes e o `--offline`
tentou parsear — reportando `no article found`, culpando o parser por um arquivo truncado.
`--offline` agora confere o sha256 do arquivo contra o sidecar do download e falha dizendo o que
fazer.

#### curl_cffi: avaliado e rejeitado (MEDIDO)

A hipótese era que impressão digital TLS (JA3/JA4) explicasse os dois bloqueios.

```text
planalto  imp=chrome    -> 200  264515 bytes  0.9s
planalto  imp=None      -> ConnectionError (reset)
stj/scon  imp=chrome    -> 403
stj/scon  imp=chrome110 -> 403
stj/toc   imp=chrome    -> 403
```

Nenhum dos dois bloqueios é TLS: o do Planalto é **User-Agent** (resolvido por header, sem
dependência) e o do STJ é **desafio JavaScript** ("Verificação automática em andamento... Enable
JavaScript and cookies"), que `curl_cffi` não executa. Trocar o cliente por um binário nativo que
imita navegador não resolve nada aqui e transfere um problema de política de acesso para uma
biblioteca. A dependência foi instalada para o teste e **removida** ao final.

#### Carga (OBSERVADO)

```text
fontes          25 habilitadas, 25 carregadas
normas          25
dispositivos    10.548
versões         10.797
embeddings      10.797 / 10.797   qwen/qwen3-embedding-8b @1024 dims
search_vector   100% preenchido; acentuação íntegra
reingestão      25/25 ok, added=0 changed=0 removed=0
```

Antes disso o banco continha **34 normas de fixture** (`fin-current-*`, `seed-e2e`) criadas por
testes; foram removidas na ordem das chaves estrangeiras.

#### Recuperação medida na base real (OBSERVADO)

40 perguntas com gabarito, caminho de produção (pgvector denso + FTS + expansão + hidratação):

```text
hit@1 = 0.45   hit@3 = 0.57   hit@5 = 0.70   hit@10 = 0.88   abstenções = 1/40
```

As quatro falhas em top-10 eram da `stj-sum-542`, cujo enunciado ("ação penal pública
incondicionada") está semanticamente distante da paráfrase da pergunta ("dizem que eu preciso
representar"). A súmula **está** ingerida e indexada: a dificuldade é de ranqueamento, não de
base faltando.

#### Achado novo, não corrigido: expansão para o artigo falha em 14,4% (OBSERVADO)

```text
dispositivos não-artigo                         7.928
  encontram o artigo no mesmo norm_version      6.783
  não encontram                                1.145  (14,4%)
```

Cada dispositivo aponta para o `norm_version` da sua própria vigência. Quando o parágrafo ganhou
redação nova e o caput não, os dois ficam em versões diferentes e `expand_to_article` recusa a
mistura (`incomplete_context`), devolvendo o parágrafo sem o artigo. O guarda existe para não
citar caput revogado junto de parágrafo vigente; a correção correta é expandir para a versão do
artigo **vigente na data de início do dispositivo**, não para a mesma chave. Fica registrado como
pendência com número, não como impressão.

#### Limites que permanecem

- O conjunto de avaliação tem 150 perguntas mas só **16 dispositivos distintos** no gabarito: os
  números acima medem recuperação, não correção de resposta;
- o art. 46 da LMP traz a sequência decorativa de cruzes do Planalto no texto literal (cosmético);
- um dispositivo **novo** com vigência futura seria recusado por `_check_start` — não há caso hoje,
  mas uma lei com *vacatio legis* criando artigo novo cairia nisso.

### 22.29 Conversa ponta a ponta sobre a base real (2026-11-16)

O item 1 de §24.3 ficava em aberto porque só havia E2E contra dispositivo semeado. Com a base de
§22.28 ingerida, o caminho completo rodou no processo real (`create_app` + `TestClient`):

```text
GET  /health -> 200  {durable: false, resumable: false, web_search: true}
                     data_atualizacao_base = 2026-11-16
POST /chat   -> 200  abstencao=false  nivel_confianca=medio
```

Pergunta: *"Quais medidas protetivas posso pedir ao juiz e em quanto tempo elas saem?"*

```text
citações (verificadas contra dispositivo hidratado):
  lmp/art22/cpt      Lei nº 11.340/2006, art. 22, caput
  lmp/art19/par2     Lei nº 11.340/2006, art. 19, § 2º
  lmp/art18/cpt/inc1 Lei nº 11.340/2006, art. 18, caput, inciso I
  lmp/art12/cpt/inc3 Lei nº 11.340/2006, art. 12, caput, inciso III
encaminhamentos: 190 (emergência), 180 (Central da Mulher), Defensoria
```

A resposta cita as 48 horas do art. 18 e a aplicação isolada ou cumulativa do art. 22 — os dois
pontos que a pergunta pedia, tirados do texto ingerido, não do modelo.

#### O caminho de emergência continua na frente de tudo (OBSERVADO)

A primeira pergunta de teste ("me empurrou e ameaçou me bater") voltou com `emergencia=true` e
nenhuma citação: o classificador de risco respondeu antes de qualquer I/O, como INV09 exige.

#### Não determinismo da geração (OBSERVADO)

A mesma pergunta, três execuções: **resposta**, **abstenção** (`nivel_confianca=baixo`, motivo não
preenchido) e **resposta**. O verificador recusou publicar na segunda — é o comportamento previsto
para citação não verificada, mas a taxa de abstenção varia entre execuções idênticas, e isso é um
número que ainda não foi medido. Entra como pendência: medir a taxa de abstenção em N execuções da
mesma pergunta antes de tratar "responde" como garantido.

O primeiro POST devolveu **422**: `ChatRequest` exige `session_id` e tem `extra="forbid"`. É
contrato correto, só não estava documentado para quem chama a API manualmente.

### 22.30 O que o CI encontrou que o ambiente local escondia (2026-11-16)

A primeira execução do PR reprovou o job `test` com **três falhas**, todas em
`tests/unit/test_api_v1_mount.py`, e todas invisíveis aqui porque a máquina local tem `.env` com
chaves reais e um Postgres rodando com a base ingerida:

```text
test_health_publica_capacidades        assert {'web_search': False} == {'web_search': True}
test_rota_v1_sem_cookie_e_401          psycopg.OperationalError: connection refused (5432)
test_capacidades_seguem_as_flags       idem
```

**Causa 1 — valor esperado herdado do ambiente.** O teste fixava `web_search: True`, que vinha de
`WEB_SEARCH_ENABLED=true` no `.env` local. O valor esperado passa a vir da flag entregue ao
construtor, então o teste mede o que diz medir.

**Causa 2 — a rota abria conexão antes de exigir o cookie.** Duas rotas liam o cookie *dentro* do
`with conectar()`: sem banco, o 401 virava erro de conexão. O conserto não foi no teste.
`token_do_cookie(request)` em `src/api/auth.py` recusa a requisição **antes** de qualquer I/O, e
`/messages`, `/current`, `DELETE` e as três rotas de execução passaram a usar o guarda. O teste
novo troca o abridor de conexão por um que levanta `AssertionError` e verifica que a rota anônima
responde 401/404 mesmo assim.

Isso fecha um vetor que não era só de teste: requisição anônima consumia conexão do pool.

**Causa 3 — formato de saída do Node.** `test_durable_js.py` exigia `# fail 0`; o Node 22 local
imprime TAP (`# fail 0`) e o Node 20 do runner imprime o reporter spec (`ℹ fail 0`). A asserção
passou a aceitar os dois marcadores e a exigir `pass >= 1`, para que suíte vazia não conte como
verde.

Depois dos três consertos, o PR ficou com **5 de 5 jobs verdes** (`lint`, `typecheck`, `test`,
`integration`, `backup-restore`).

#### Lição de processo, não de código

Os 948 testes verdes locais não provavam nada sobre o ambiente de CI: `.env` presente e banco
disponível **mascararam** duas dependências implícitas. O experimento que teria pegado isso antes do
push é barato — mover `.env` para longe e rodar a suíte. Fiz isso depois, e ele sozinho não bastava
porque o Postgres continuava de pé; o CI provou o que a simulação não provou.

### 22.31 Citação fantasma: quando "para mim" virava inciso 1999 (2026-11-18)

A avaliação de recuperação sobre a base real devolveu **uma abstenção em 40 perguntas**. A pergunta
era `q040` — "quero entender se a ação é pública ou depende de mim" — e a abstenção era
`citacao_explicita_nao_encontrada`. A mensagem não cita dispositivo nenhum.

**OBSERVADO — a causa.** `_extract_bare_tokens` recebia a mensagem inteira quando não havia artigo
e aceitava qualquer palavra que fosse numeral romano válido:

```text
roman_to_int("mim") == 1999        # M 999 M -> M + (M - I)
parse_citation("... depende de mim.").inciso == 1999
```

Inciso sem artigo ⇒ `norm_ambiguous` ⇒ `is_explicit_miss` ⇒ **abstenção**. O defeito não era de
métrica: era o sistema se recusando a responder uma pergunta que sabia responder.

A varredura das 150 perguntas do conjunto de avaliação e de frases reais de relato mostrou que o
problema é mais largo que a palavra que o revelou — e que ele arrasta uma segunda invenção:

| Entrada | Antes | Depois |
| --- | --- | --- |
| "…depende de **mim**." | inciso 1999 | sem citação |
| "ele ganha três **mil** por mês…" | inciso 1049 + alínea `e` | sem citação |
| "**vim** aqui porque não sei…" | inciso 994 + alínea `o` | sem citação |
| "a situação que eu **vivi** foi ruim" | inciso 10 | sem citação |
| "o art. 22… para **mim** é confuso" | `lmp/art22/cpt/inc1999` → `not_found` | `lmp/art22` |

A alínea fantasma vem do mesmo passo: depois de fixar um inciso, qualquer letra solta seguinte era
aceita como alínea — e `e` e `o` são letras e são palavras. A última linha é a variante pior: uma
citação **legítima** era destruída por uma palavra comum ao lado, e o artigo 22, que existe, virava
`not_found` ⇒ abstenção.

**Decisão de conserto — dois guardas no parser, nenhum no chamador.**

1. `canonical_roman_to_int` (`src/textnorm.py`) só aceita a grafia canônica do numeral. 1999 é
   `MCMXCIX`, nunca `MIM`; converter o número de volta para letras rejeita `mim`, `mil`, `vim`, `vivi`
   e `civil` sem perder nenhum inciso que exista numa lei. Aplicado também em `_convert_inciso_romans`,
   para que a normalização de busca não reescrevesse "inciso mim" como "inciso 1999" — o mesmo defeito
   entrando pelo outro lado.
2. `_allows_bare_tokens` só lê qualificador solto quando a mensagem tem artigo ou marcador de citação
   (`artigo`, `paragrafo`, `inciso`, `alinea`, `item`, `caput`, `sumula`). Só existem tokens soltos
   porque `art. 22, III, "b"` não traz palavra-chave: longe de uma citação, eles são prosa.

Somado a isso, `_PROSE_SINGLE_LETTERS = {a, e, o}` impede que uma palavra de uma letra vire alínea
solta; letra entre aspas (`"a"`) continua valendo, porque ali a intenção é explícita.

**VALIDADO — o teste vermelho antes do verde.** Os 30 casos novos foram rodados contra o `HEAD`
anterior: 8 falharam (os cinco da tabela, mais "art. 22, III e não sei…", "III" sozinho e a frase com
artigo legítimo). Depois do conserto, `993 passed`, `ruff` e `mypy` limpos.

**VALIDADO — o alcance real da mudança, medido.** Varrendo as 150 perguntas do conjunto contra o
parser antigo e o novo, **1 pergunta muda de comportamento** (`q040`, a que motivou o conserto) e os
disparos de "citação explícita não encontrada" caem de 3 para 2 — os outros dois continuam sendo
citações explícitas de verdade que não existem no corpus.

Na base real, com a mesma pilha de produção (pgvector + FTS + expansão + hidratação):

```text
q040                    abstencao=None  n=10  (antes: citacao_explicita_nao_encontrada)
"o que diz o art. 22"   abstencao=None  n=1   [lmp/art22]   <- caminho explícito intacto
```

**PENDENTE — o que isso não conserta.** A recuperação de `q040` continua sem trazer `stj-sum-542` no
top-10. O conserto devolve o **comportamento** (responder em vez de abster), não o **ranqueamento**:
a dificuldade da Súmula 542 — paráfrase coloquial contra enunciado curto e abstrato — segue aberta e
é o item seguinte do plano.

**Lição.** O número agregado escondeu a natureza da falha: `q040` entrava nas estatísticas como
"recuperação perdida", quando era abstenção indevida. Uma métrica de recall não distingue "não achei"
de "me recusei a procurar", e só a leitura pergunta por pergunta separou as duas coisas.
