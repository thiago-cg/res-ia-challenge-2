# Assistente jurídica para violência doméstica — protótipo RAG

Protótipo local de orientação jurídica informativa para mulheres em situação de
violência doméstica. O sistema recupera dispositivos legais oficiais
(Lei Maria da Penha, Código Penal, Código de Processo Penal, súmulas do STJ e
atos do CNJ), responde com citações montadas a partir de metadados e encaminha
para atendimento humano quando necessário.

> **Aviso permanente:** esta é uma orientação informativa e **não substitui
> atendimento jurídico individual**. Não é parecer, não é sentença e não
> substitui a Defensoria Pública. **Se você está em perigo agora, ligue 190.**
> A Central de Atendimento à Mulher é o **180**.

**Status em 2026-11-05:** protótipo técnico. Métricas de avaliação e revisão
jurídica humana estão **PENDENTES**. Veja [Estado atual](#estado-atual-honesto)
antes de usar qualquer número deste repositório.

## O que é

- Um assistente que **explica direitos, prazos e caminhos** com base em textos
  legais oficiais.
- Um sistema que **cita o dispositivo recuperado**: o LLM devolve apenas
  `device_id`; a citação canônica é renderizada pelo sistema a partir do banco.
- Um sistema que **se abstém** quando não há evidência suficiente e que
  **desvia risco imediato para 190/180 antes de qualquer busca**.

## O que não é

- Não é advogada, Defensoria, juíza ou órgão de segurança pública.
- Não dá veredito sobre o caso, não promete resultado e não substitui
  atendimento presencial.
- Não usa Jusbrasil nem faz scraping de doutrina. Doutrina está fora do MVP por
  restrição de licença.
- Não registra a pergunta por padrão; veja [LGPD e segurança](#lgpd-e-segurança).
- Não está pronto para publicação: **não houve revisão jurídica humana** e os
  gates **G4 e G6 não foram atingidos**.

## Estado atual (honesto)

| Item | Estado real |
| --- | --- |
| Caminho fallback (FTS/RRF + denso) | Executado de ponta a ponta contra Postgres e Qdrant reais. O denso medido é o Qdrant 4096d (`DENSE_BACKEND=qdrant`); o Harrier local não foi usado. |
| Caminho alvo (pplx 9B/0.6B + Qdrant) | Código presente, atrás de `RETRIEVAL_PATH=target`. O app padrão não monta o searcher Qdrant; é preciso injetar um pipeline. Sem GPU/safetensors validados. |
| Ingestão | CLI completa com `--stage download|parse|validate|load|all`, `--offline`, JSONL atômico (`--out-jsonl`) e carga idempotente. Coberta por testes sem rede/DB; a execução ao vivo não foi feita neste ambiente. |
| Índice | `src.index.run --path fallback` existe, mas exige `EMBEDDING_MODEL_REVISION` pinado e o extra `ml`. |
| Avaliação | As 20 perguntas de `data/eval/questions.jsonl` foram medidas contra Postgres/Qdrant ao vivo (ver *Postgres FTS + Qdrant*). As 150 continuam sem execução. O conjunto é pequeno (10 respondíveis) e as regras de expansão foram escritas sobre ele: são números in-sample, não um benchmark cego. |
| Revisão jurídica | **PENDENTE**. Nenhuma advogada, defensora ou pessoa da rede de atendimento revisou prompt, textos ou respostas. Não há parecer. |
| Modelos locais | Os artefatos locais são **GGUF** (llama.cpp). O caminho alvo precisa de **safetensors**. GGUF levanta `ModelFormatError`; o fallback é o padrão. |
| Docker/Postgres/Qdrant | `docker-compose.yml` e CI existem, mas **não há Docker, Postgres ou Qdrant ao vivo** no ambiente em que este status foi escrito. Testes de integração não foram executados aqui. |
| Observabilidade | Módulos de log estruturado e middleware existem, com testes. `create_app` instala `RequestContextMiddleware` e `SecurityHeadersMiddleware`; não houve execução ponta a ponta ao vivo neste ambiente. |
| LLM | Padrão `LLM_PROVIDER=mock`. Os provedores `local`, `api` e `openrouter` existem; `openrouter` usa as chaves `OPENROUTER_*` e permite rodar sem modelos locais. O smoke ao vivo depende de chave e rede e **não foi executado** para produzir métricas. |

## Arquitetura e fluxo

**Postgres é a fonte da verdade.** Normas, dispositivos, versões por vigência,
citações, explicações e auditoria ficam em tabelas relacionais. Cada texto é
identificado pelo par `(device_id, norm_version_id)`; o LLM nunca escolhe a
versão.

- **Fallback (padrão, sem GPU):** embeddings densos Harrier 0.6B em `pgvector`,
  busca textual FTS, fusão RRF, rerank opcional e top 10.
- **Alvo (atrás de flag):** pplx 9B indexa e pplx 0.6B consulta no mesmo espaço
  multivector; Qdrant guarda os vetores `late` e `bm25`. Requer GPU e
  safetensors. `RETRIEVAL_PATH=target` sozinho não basta: o app padrão exige
  injeção de um searcher Qdrant.
- **Emergência não passa pelo RAG:** o roteador de risco roda antes de qualquer
  busca e devolve o bloco fixo com 190, 180, 100 e 197.

Fluxo de uma pergunta:

```text
mensagem
→ roteador de risco (emergência? responde 190/180 e encerra)
→ citação explícita (art. 7º, 24-A, inciso III)
→ entendimento da consulta e subperguntas
→ busca híbrida (fallback ou alvo)
→ dedupe/expansão por artigo → hidratação por (device_id, norm_version_id)
→ prompt com documentos delimitados
→ LLM devolve JSON com IDs
→ validação do schema → verificador (ID, versão, suporte)
→ resposta renderizada + fontes, ou abstenção segura
```

## Requisitos

- Python **3.12** e [uv](https://docs.astral.sh/uv/).
- Docker (opcional; necessário para Postgres/Qdrant locais).
- GPU + checkpoints **safetensors** apenas para o caminho alvo.
- Rede para a ingestão das fontes oficiais e, opcionalmente, para o OpenRouter.

## Quickstart em máquina limpa

Os comandos abaixo são de PowerShell (Windows). Em Linux/macOS, troque
`Copy-Item` por `cp` e a atribuição de ambiente por `export`.

### 1. Dependências

```powershell
uv sync --extra dev
```

Para carregar embeddings reais (fallback), instale o extra `ml`:

```powershell
uv sync --extra dev --extra ml
```

O extra `dev` sozinho **não** instala `sentence-transformers`; sem `ml`, o
índice real não funciona.

### 2. Configuração

```powershell
Copy-Item .env.example .env
```

Edite `.env` e **pinne** `EMBEDDING_MODEL_REVISION` com um commit/tag. Vazio ou
`main` faz o encoder real falhar de propósito:

```text
EMBEDDING_MODEL_REVISION=<commit-ou-tag>
```

O padrão `LLM_PROVIDER=mock` não precisa de chave. Para LLM local/API, use
`LLM_BASE_URL` e `LLM_API_KEY`; para rodar sem modelos locais, veja
[Rodando com OpenRouter](#rodando-com-openrouter).

### 3. Infra local

Fallback (apenas Postgres):

```powershell
docker compose up -d db
```

Alvo (Postgres + Qdrant):

```powershell
docker compose --profile target up -d
```

### 4. Migrações

`scripts/apply_migrations.py` **não lê `.env`**; ele usa `DATABASE_URL` do
ambiente ou `--database-url`. O default local é:

```powershell
$env:DATABASE_URL = "postgresql://app:app@localhost:5432/violencia"
uv run python scripts/apply_migrations.py
```

Alternativa sem exportar a variável:

```powershell
uv run python scripts/apply_migrations.py --database-url "postgresql://app:app@localhost:5432/violencia"
```

Dentro de um virtualenv ativado, `python scripts/apply_migrations.py` também
funciona. O script aplica todos os `migrations/*.sql` em ordem e faz commit por
arquivo.

### 5. Ingestão (download, parsing, validação e carga)

O comando padrão roda o pipeline inteiro (`--stage all`): baixa, parseia,
valida e carrega no Postgres.

```powershell
uv run python -m src.ingest.run --priority P0
```

Opções de seleção: `--source <id>`, `--priority P0|P1` ou `--all` (mutuamente
exclusivas), além de `--manifest`, `--dest-dir`, `--timeout` e `--retries`. Os
arquivos brutos vão para `data/raw/` com sidecar `.meta.json` e hash SHA-256; o
download é idempotente.

`--stage` escolhe até onde ir:

```powershell
uv run python -m src.ingest.run --source lmp --stage download
uv run python -m src.ingest.run --source lmp --offline --stage parse --out-jsonl data/processed
uv run python -m src.ingest.run --priority P0 --offline --stage load --database-url "postgresql://app:app@localhost:5432/violencia"
```

- `download`: apenas baixa (não parseia).
- `parse`: baixa (ou usa `--offline`) e parseia; não valida nem carrega.
- `validate`: para no checklist de validação.
- `load` / `all`: baixa (ou `--offline`), parseia, valida e carrega.
- `--offline`: não baixa; usa `data/raw/<source>.*` e falha se o arquivo não
  existir.
- `--out-jsonl PATH`: grava um JSONL atômico por fonte em
  `PATH/<source>.jsonl` (com um único source, `PATH` pode ser um arquivo
  `.jsonl`). Cada linha traz a versão parseada e os campos de identidade do
  dispositivo usados pelo loader.
- `--database-url`: cai para `DATABASE_URL` e para o default de `Settings`. Em
  `load`/`all`, uma conexão inacessível encerra com código 1 e mensagem clara.

O relatório por fonte mostra `devices`, `changed` e `errors`; qualquer falha
retorna código 1. A carga usa o mesmo `load_parse_result` do índice e registra
`ingest_runs` com `record_ingest_run` (`running` → `ok`/`error`).

### 6. Índice fallback

```powershell
uv run python -m src.index.run --path fallback
```

Pré-requisitos: `EMBEDDING_MODEL_REVISION` pinado, extra `ml` instalado e
dispositivos já carregados. Opções: `--source`, `--database-url`,
`--batch-size`. A CLI imprime `indexed`, `skipped`, `errors` e modelo; retorna
código 1 se houver erro.

Caminho alvo (só com Qdrant e encoder multivector safetensors):

```powershell
uv run python -m src.index.run --path target
```

Sem um encoder que exponha `encode_multivectors` com vetores de 128 dimensões,
o comando falha com `ModelFormatError`. Os GGUF locais não servem.

### 7. API e interface

```powershell
uv run uvicorn src.api.main:app --no-access-log
```

Em outro terminal:

```powershell
uv run streamlit run web/app.py
```

A UI fala com `http://localhost:8000` por padrão; defina `API_URL` para apontar
para outro endereço. Endpoints: `POST /chat`, `GET /health`,
`GET /sources/{device_id}?version=&date=`.

`--no-access-log` evita que o uvicorn registre a query string no log de acesso.
O `/health` reporta `degraded` quando Postgres ou Qdrant estão inacessíveis;
nunca finge `ok`.

### 8. Testes e qualidade

```powershell
uv run pytest -m "not integration"
uv run pytest -m integration
uv run ruff check .
uv run ruff format --check .
uv run mypy src
```

`pytest -m integration` exige Postgres/Qdrant vivos e não foi executado no
ambiente deste status. O CI define os serviços e aplica as migrações antes.

## Rodando com OpenRouter

O OpenRouter permite usar chat e embeddings densos sem baixar modelos locais.
Ele é compatível com a API da OpenAI em `https://openrouter.ai/api/v1`.

Configure o ambiente (ou copie o bloco `OPENROUTER_*` de `.env.example` para
`.env`):

```powershell
$env:LLM_PROVIDER = "openrouter"
$env:EMBEDDING_PROVIDER = "openrouter"
$env:RETRIEVAL_PATH = "fallback"
$env:OPENROUTER_API_KEY = "<sua-chave>"
```

Defaults: chat `openai/gpt-4o-mini`; embeddings
`openai/text-embedding-3-small` com `OPENROUTER_EMBEDDING_DIMENSIONS=1024`
(compatível com `vector(1024)` de `migrations/001_init.sql`). `OPENROUTER_*`
também aceita modelo, base URL, lote, timeout, retries e os cabeçalhos
opcionais de site/app.

Smoke ao vivo (falha com código 1 e mensagem clara se a chave não existir ou a
API não responder):

```powershell
uv run python scripts/check_openrouter.py
uv run pytest -m integration
```

O teste `tests/integration/test_openrouter_live.py` é pulado quando
`OPENROUTER_API_KEY` não está definido; quando definido, faz uma chamada de chat
e uma de embeddings com prompt mínimo.

> **Privacidade:** enviar perguntas de vítimas a um terceiro exige contrato de
> retenção zero, sem treinamento com os dados e jurisdição compatível. Por
> padrão o código pede `OPENROUTER_DATA_COLLECTION=deny` e `OPENROUTER_ZDR=true`,
> mas essas preferências precisam ser validadas com o provedor e com o contrato;
> não são garantia jurídica. Se isso não estiver assegurado, rode LLM e embedder
> localmente.

O caminho alvo continua indisponível: o OpenRouter não oferece os modelos
multivector `pplx-embed-v2-late` usados por `RETRIEVAL_PATH=target`. Com
`EMBEDDING_PROVIDER=openrouter` e `RETRIEVAL_PATH=target`,
`build_default_pipeline` levanta `ValueError` e pede
`RETRIEVAL_PATH=fallback`.

## Variáveis de ambiente

Todas as chaves de `.env.example`. O default entre parênteses é o usado pelo
código quando a variável não existe.

| Variável | Default | Para que serve |
| --- | --- | --- |
| `RETRIEVAL_PATH` | `fallback` | `fallback` (pgvector/FTS) ou `target` (Qdrant/9B). O alvo ainda exige injeção de searcher. |
| `EMBEDDING_PROVIDER` | `harrier` | `harrier` no fallback; `pplx` para os modelos pplx; `openrouter` para embeddings densos remotos. |
| `EMBEDDING_MODEL_REVISION` | vazio | Commit/tag do modelo. **Obrigatório para indexar**; vazio ou `main` levanta erro. Ignorado com `EMBEDDING_PROVIDER=openrouter`. |
| `LLM_PROVIDER` | `mock` | `mock`, `local`, `api` ou `openrouter`. `openrouter` usa as chaves `OPENROUTER_*`. |
| `MAX_DEVICES` | `10` | Máximo de dispositivos no contexto/resposta. |
| `MAX_CONTEXT_TOKENS` | `6000` | Orçamento de tokens do contexto. |
| `MAX_SUBQUESTIONS` | `3` | Máximo de subperguntas (contrato limita a 3). |
| `MAX_AGENT_LOOPS` | `3` | Limite de loops do agente; presente na config. |
| `DATABASE_URL` | `postgresql://app:app@localhost:5432/violencia` | Postgres, fonte da verdade. |
| `QDRANT_URL` | `http://localhost:6333` | Qdrant do caminho alvo e do health check. |
| `PPX_9B_MODEL_PATH` | vazio | Diretório **safetensors** do pplx 9B (indexação alvo). Valor terminado em `.gguf` é rejeitado. |
| `PPX_06B_MODEL_PATH` | vazio | Diretório **safetensors** do pplx 0.6B (consulta alvo/rerank). Valor terminado em `.gguf` é rejeitado. |
| `HARRIER_MODEL_PATH` | vazio | Diretório **safetensors** do Harrier; vazio usa `microsoft/harrier-oss-v1-0.6b`. Valor terminado em `.gguf` é rejeitado. |
| `LLM_MODEL` | vazio | Nome do modelo do provedor LLM; com `mock`, vira `mock`. Com `openrouter`, é o fallback quando `OPENROUTER_MODEL` está vazio. |
| `LLM_BASE_URL` | vazio | Base URL de um servidor OpenAI-compatible/Ollama para `LLM_PROVIDER=local` ou `api`. |
| `LLM_API_KEY` | vazio | Chave do provedor local/API. Para OpenRouter, use `OPENROUTER_API_KEY`. |
| `OPENROUTER_API_KEY` | vazio | Chave do OpenRouter. Obrigatória apenas ao construir os clientes OpenRouter; `Settings` não falha sem ela. |
| `OPENROUTER_BASE_URL` | `https://openrouter.ai/api/v1` | Base URL da API do OpenRouter. |
| `OPENROUTER_MODEL` | `openai/gpt-4o-mini` | Modelo de chat; vazio cai para `LLM_MODEL` e depois para o default. |
| `OPENROUTER_EMBEDDING_MODEL` | `openai/text-embedding-3-small` | Modelo de embeddings densos. |
| `OPENROUTER_EMBEDDING_DIMENSIONS` | `1024` | Dimensão pedida ao provedor; precisa bater com o `vector(N)` indexado. |
| `OPENROUTER_BATCH_SIZE` | `32` | Textos por requisição de embeddings. |
| `OPENROUTER_TIMEOUT` | `60` | Timeout em segundos das requisições de embeddings. |
| `OPENROUTER_MAX_RETRIES` | `2` | Tentativas extras em 429/5xx/timeout; `0` desliga. |
| `OPENROUTER_DATA_COLLECTION` | `deny` | Preferência `provider.data_collection` (`deny` ou `allow`). |
| `OPENROUTER_ZDR` | `true` | Preferência `provider.zdr` (zero data retention). |
| `OPENROUTER_SITE_URL` | vazio | Cabeçalho opcional `HTTP-Referer`. |
| `OPENROUTER_APP_NAME` | vazio | Cabeçalho opcional `X-Title`. |
| `LOG_LEVEL` | `INFO` | Nível do logger. |
| `LOG_QUESTION_TEXT` | `false` | Se `true`, permite logar texto de pergunta **com PII redigida**. Padrão: descartar. |
| `LOG_RETENTION_DAYS` | `7` | Retenção de logs; `0` significa sem persistência. Lido do ambiente do processo, não do `.env` por `src.obs.logging`. |

Observações de configuração:

- `src.config.Settings` carrega `.env` (pydantic-settings). `scripts/apply_migrations.py`
  e `src.obs.logging` leem o ambiente do processo; exporte as variáveis nesses casos.
- `LOG_QUESTION_TEXT` e `LOG_RETENTION_DAYS` não passam por `Settings`; são lidos
  diretamente por `src.obs.logging`.
- `MAX_AGENT_LOOPS` está na configuração, mas o pipeline atual não executa um loop
  agêntico amplo.
- `LLM_PROVIDER=openrouter`/`EMBEDDING_PROVIDER=openrouter` não exigem chave na
  construção de `Settings`; `get_llm`/`get_encoder` falham nomeando
  `OPENROUTER_API_KEY` apenas quando o cliente é criado. O caminho alvo é
  rejeitado porque não há modelo multivector no OpenRouter.

## Modelos e formatos

- Os caminhos `LOCAL_06B_GGUF` e `LOCAL_9B_GGUF` em `src/config.py` apontam para
  diretórios **GGUF** da máquina de desenvolvimento. Eles não são baixados pelo
  projeto e não são portáveis.
- `sentence-transformers` não carrega GGUF. Um valor de configuração terminado
  em `.gguf` em `PPX_9B_MODEL_PATH`, `PPX_06B_MODEL_PATH` ou
  `HARRIER_MODEL_PATH` levanta `ModelFormatError` antes de qualquer
  download/carga. Um diretório que apenas contém arquivos GGUF não é detectado
  por essa checagem; aponte para um diretório safetensors ou use o fallback.
- O caminho alvo exige checkpoints **safetensors** do pplx 9B/0.6B e um encoder
  multivector. O caminho fallback usa Harrier denso em `pgvector`.
- Sem `EMBEDDING_MODEL_REVISION` pinado, `get_encoder` falha; na API, a factory
  preguiçosa devolve abstenção segura `servico_indisponivel` em vez de fingir
  recuperação.

## Avaliação

O harness e os conjuntos existem:

- `data/eval/questions.jsonl`: 20 perguntas semeadas.
- `data/eval/questions_150.jsonl`: 150 perguntas (20 semeadas + 130 sintéticas).
- `data/eval/regressions.jsonl`: regressões legais R1–R6 e casos extras.
- `src/eval/run.py` e `src/eval/metrics.py`: recall@10, MRR, nDCG, citação,
  groundedness, abstenção, emergência e latência.

Comando do harness:

```powershell
uv run python -m src.eval.run --questions data/eval/questions_150.jsonl --out data/eval/last_run.json
```

O adaptador real (`src.api.main.build_eval_pipeline`) existe e mapeia a saída do
pipeline para o harness. Sem Postgres, encoder ou `EMBEDDING_MODEL_REVISION`
válidos, o comando falha com mensagem clara em vez de fingir execução. O harness
também aceita um pipeline injetado nos testes. **Nenhuma métrica foi produzida.**

`G4` (eval 20 + revisão humana), `G6` (150 + parecer) e a revisão jurídica humana
permanecem **PENDENTES**. Os números de `docs/08` são metas, não resultados.

## LGPD e segurança

- **Sem PII por padrão:** `LOG_QUESTION_TEXT=false` descarta pergunta, resposta,
  prompt e corpo nos logs. Com opt-in, `redact_pii` ainda substitui CPF,
  telefone, e-mail e CEP.
- **Retenção:** `LOG_RETENTION_DAYS=7` por padrão; `0` significa não persistir.
  Ainda não há sink de arquivo/banco: a retenção é uma obrigação contratual para
  quem criar um sink.
- **APIs externas:** só com contrato de retenção zero, sem treinamento com os
  dados, jurisdição compatível, minimização da pergunta e trilha de auditoria.
   Caso contrário, embedder e LLM devem rodar localmente. Neste branch, o LLM
   padrão é `mock`; o OpenRouter é opt-in e as preferências
   `OPENROUTER_DATA_COLLECTION=deny`/`OPENROUTER_ZDR=true` precisam ser
   confirmadas no contrato (veja [Rodando com OpenRouter](#rodando-com-openrouter)).
- **Emergência:** o bloco com 190/180/100/197 é avaliado antes do RAG e não toca
  banco, busca ou LLM.
- **UI:** a barra lateral repete o aviso de não substituição e orienta a não
  informar nome, CPF, endereço, telefone ou documentos.
- **Observabilidade:** `create_app` instala `RequestContextMiddleware` e
  `SecurityHeadersMiddleware`; `X-Request-ID` é propagado e há teste de API.
  Ainda não há sink de retenção de logs nem execução ao vivo aqui.

## Backup e restauração

Os scripts usam `pg_dump`/`pg_restore` em formato custom e gravam um sidecar
`.sha256`.

Linux/macOS/WSL:

```bash
export DATABASE_URL="postgresql://app:app@localhost:5432/violencia"
sh scripts/backup.sh
sh scripts/restore.sh backups/violencia-<timestamp>.dump
```

Windows (PowerShell):

```powershell
$env:DATABASE_URL = "postgresql://app:app@localhost:5432/violencia"
pwsh ./scripts/backup.ps1
```

Não existe `restore.ps1` neste branch. No Windows, use `pg_restore` diretamente
ou rode `scripts/restore.sh` no WSL/Git Bash.

`restore.sh` recusa bancos cujo nome não contenha `test` ou `restore`. Para um
restore intencional em produção, defina `ALLOW_PROD_RESTORE=1` — não faça isso
por acidente. O drill de backup/restore está definido no job `backup-restore` do
CI, mas **não foi executado no ambiente deste status**.

## Limitações e próximos passos

Limitações atuais:

- A ingestão ao vivo (download das fontes oficiais + carga no Postgres) não foi
  executada neste ambiente; os testes de parsing/carga usam mocks.
- O caminho alvo (9B/Qdrant) não está operacional com os artefatos locais; os
  GGUF não servem e não há safetensors validados.
- O caminho alvo de recuperação não é montado pelo `create_app` padrão; exige
  injeção de pipeline/searcher.
- O adaptador de avaliação existe, mas as métricas seguem pendentes: não houve
  execução contra Postgres/Qdrant ao vivo.
- OpenRouter implementado e coberto por testes com httpx mockado, mas o smoke ao
  vivo (`scripts/check_openrouter.py` / `pytest -m integration`) não foi
  executado neste ambiente; não há métricas com OpenRouter. O caminho alvo
  continua indisponível no OpenRouter (sem modelo multivector `pplx-v2-late`).
- Middlewares de request ID/segurança estão ligados em `create_app`, mas não
  houve validação em execução ao vivo.
- Nenhuma revisão jurídica humana; nenhum gate G4/G6.

Próximos passos, na ordem:

1. Criar um sink de retenção de logs e validar `X-Request-ID` em execução ao vivo.
2. Rodar um smoke de ingestão real (`--stage all`) → índice com Postgres vivo.
3. Conseguir checkpoints safetensors e executar o smoke 9B/0.6B (G5).
4. Rodar as 150 perguntas com `build_eval_pipeline` contra Postgres/Qdrant.
5. Submeter prompt, textos e respostas à revisão jurídica humana (G4/G6).

## Licença e proveniência

- **Textos oficiais:** leis, decretos, constituições e atos oficiais não são
  protegidos por direitos autorais nos termos do art. 8º, IV, da Lei nº
  9.610/1998. Ainda assim, confira sempre a fonte oficial e a data de vigência;
  este repositório não dá parecer sobre licenciamento.
- **Sem Jusbrasil:** não há scraping nem incorporação de doutrina do Jusbrasil.
- **Fixtures sintéticas:** as 130 perguntas sintéticas de
  `data/eval/questions_150.jsonl` são geradas pelo projeto para teste, marcadas
  `fonte: "sintetica"` e `revisao: "pendente"`. Não são parecer jurídico nem
  respostas validadas.
- **Semente curada:** `data/seed/stf-adi-4424.json` é curada manualmente, com
  proveniência, e está `pendente_de_carga`; não foi raspada.
- **Licença do código:** não há arquivo `LICENSE` neste repositório; o código
  não está licenciado publicamente até que uma licença seja adicionada.

## Documentação

- [Índice da documentação](docs/README.md)
- [Arquitetura e stack local](docs/02-arquitetura-e-stack-local.md)
- [Dados e fontes](docs/03-dados-e-fontes.md)
- [Geração, citações e segurança](docs/06-geracao-citacoes-e-seguranca.md)
- [Avaliação](docs/08-avaliacao.md)
- [Plano de implementação](docs/10-plano-implementacao.md)


## Postgres FTS + Qdrant (production path)

The production-shaped path uses the real Postgres full-text search and a real
Qdrant dense collection. The fallback `pgvector` column remains in the schema
for compatibility, but it is not used when `DENSE_BACKEND=qdrant`.

- Lexical: `to_tsvector('portuguese', search_text)` + `websearch_to_tsquery`
  + `ts_rank_cd` in Postgres.
- Dense: Qdrant collection `devices_qdrant_dense_current` (alias), Qwen3
  Embedding 8B, 4096 dimensions, cosine, float16.
- Fusion: RRF over Postgres FTS and Qdrant dense; hydration by
  `(device_id, norm_version_id)` from `device_versions`.
- Query rewrite: `expand_legal_query` maps colloquial victim language to legal
  vocabulary deterministically; an LLM rewrite remains optional.
- Version filter: `data_fato` uses the same window as the SQL path; `None`
  means current (`vigente`/`alterado`).

Environment:

```env
RETRIEVAL_PATH=fallback
DENSE_BACKEND=qdrant
EMBEDDING_PROVIDER=openrouter
OPENROUTER_EMBEDDING_MODEL=qwen/qwen3-embedding-8b
OPENROUTER_EMBEDDING_DIMENSIONS=4096
OPENROUTER_QUERY_INSTRUCTION=Instruct: Dada uma pergunta jurídica de uma vítima de violência doméstica, recupere o dispositivo legal que a responde. Query: 
DATABASE_URL=postgresql://app:app@localhost:5432/violencia
QDRANT_URL=http://localhost:6333
```

Local run with real services:

```powershell
# 1. Postgres + pgvector (local pgserver) and Qdrant v1.15.3
#    See docs/02 for docker compose; this workspace used pgserver and the
#    qdrant Windows binary for the live benchmark.
uv run python scripts/apply_migrations.py --database-url $env:DATABASE_URL

# 2. Load the validated corpus with the production ingest path.
#    --all requires every enabled raw file; use --source for a subset when a
#    download is unavailable.
uv run python -m src.ingest.run --all --offline --stage load `
  --database-url $env:DATABASE_URL

# 2b. STJ súmulas are a curated seed (no raw PDF in this workspace)
uv run python scripts/load_parsed_corpus.py --sources "" `
  --database-url $env:DATABASE_URL

# 3. Embed into Qdrant (production indexer)
uv run python -m src.index.run --path qdrant-dense `
  --database-url $env:DATABASE_URL --qdrant-url $env:QDRANT_URL

# 4. Benchmark against real Postgres FTS + Qdrant
uv run python scripts/benchmark_production.py `
  --database-url $env:DATABASE_URL --qdrant-url $env:QDRANT_URL
```

The benchmark report is written to `data/eval/benchmark_production.md` and
`data/eval/benchmark_production.json`. `gold` recall is 1.0 by construction
(gold devices are supplied); use `dense`/`hybrid` for retrieval and `gold` for
generation/citation quality.

### Lexical normalization

`search_text` is stored without accents, because the loader builds it with
the shared `normalize_search_text`. The query side must use the same
function: `fts_search` builds a disjunctive `websearch_to_tsquery` input
from the content terms (`build_fts_query`) instead of passing the raw
question. `websearch_to_tsquery` joins bare terms with AND, so a full
question used to become a ~19-term conjunction and every lexical query
returned zero rows.

### Ablation

The deterministic query rewrite is switchable, so its contribution can be
measured instead of assumed:

```powershell
uv run python scripts/benchmark_production.py `
  --database-url $env:DATABASE_URL --qdrant-url $env:QDRANT_URL `
  --scenarios dense,hybrid --no-expansion `
  --out data/eval/benchmark_production_noexp.json `
  --md data/eval/benchmark_production_noexp.md
```

Result on the same 20 questions (retrieval only, `gold` omitted because it is
tautological):

| Scenario | Expansion | Recall@10 device | Recall@10 article | MRR@10 |
| --- | --- | ---: | ---: | ---: |
| dense | on | 0.850 | 1.000 | 0.592 |
| dense | off | 0.583 | 0.733 | 0.483 |
| hybrid | on | 0.750 | 0.950 | 0.512 |
| hybrid | off | 0.550 | 0.683 | 0.398 |

The entire gain comes from the rewrite, and the rewrite was authored while
looking at these questions: both splits improve, so the `dev`/`test` split
does not protect anything here. Two further caveats follow from the same
runs: `hybrid` is worse than `dense` in both settings, so the fixed lexical
leg is real but does not yet earn its place in the fusion; and the
device-level misses concentrate in the article-level dedupe, since
`Recall@10 article` reaches 1.000 where the device-level number is 0.850.


### Retrieval validation on the 110 answerable questions

The 20-question set was used to author the query rewrite, so it overstates
quality. `data/eval/questions_150.jsonl` has 110 answerable questions and is
the honest estimate (retrieval only, no LLM):

| Configuration | Recall@10 | Questions fully retrieved |
| --- | ---: | ---: |
| dense, no dedupe | 0.771 | 74/110 (67%) |
| dense, dedupe 1 per article (old default) | 0.677 | 57/110 (52%) |
| dense, dedupe 3 per article, article first (current) | **0.776** | 74/110 (67%) |
| hybrid RRF equal weights (old default) | 0.588 | 45/110 (41%) |
| hybrid RRF lexical weight 0.2 (current) | ~0.67 | ~57/110 (52%) |

Three changes follow from this table and are now the defaults:
`max_devices_per_article=3` (the gold set is device-level, so one slot per
article drops the article's second paragraph), article-first ordering inside
the group (a leaf usually outranks its own article, which the gold set often
names), and `hybrid_lexical_weight=0.2` (equal-weight RRF let a weak
`ts_rank_cd` ranking outvote the dense list).

Where the remaining recall is:

| k | Recall@10 | Questions fully retrieved |
| --- | ---: | ---: |
| 10 | 0.771 | 67% |
| 20 | 0.852 | 76% |
| 30 | 0.886 | 83% |
| 50 | 0.905 | 85% |

The gold device is in the dense top-50 for 85% of the questions but in the
top-10 for 67%, so the remaining loss is ordering. An LLM reranker over the
top-30 was tested and does **not** help (0.738 vs 0.736 recall@10 with the
pool hydrated, 0.705 without): `RERANK_PROVIDER=llm` exists but stays off.

On the 20-question production set, with the defaults above, the retrieval
stage now saturates:

| Scenario | Recall@10 | Recall per question | Citation coverage | Questions passing | p50 |
| --- | ---: | ---: | ---: | ---: | ---: |
| dense | 1.000 | 1.000 | 0.917 | 18/20 (90%) | 10.8 s |
| hybrid | 1.000 | 1.000 | 0.867 | 18/20 (90%) | 8.2 s |
| gold | 1.000 | 1.000 | 0.817 | 17/20 (85%) | 0 s |

`recall_per_question` is the share of questions whose whole gold set is in
the top-10; "questions passing" is the harness notion (gold retrieved **and**
cited, emergency routed, out-of-scope abstained). The remaining dense
failures are citation-side (`q001`, `q008`), not retrieval.

This 90% is on the 20-question set that the query rewrite was written
against; the 110-question table above (67% fully retrieved) is the honest
generalisation estimate, and the gap between them is the overfitting that
still has to be paid down.
### Tried and rejected (measured, so nobody repeats it)

| Change | Measurement | Decision |
| --- | --- | --- |
| LLM query rewrite replacing the deterministic rules (qwen-2.5-7b, query-understanding prompt) | recall@10 0.433 vs 0.733 | off |
| Same with a dedicated retrieval-rewrite prompt | 0.461 vs 0.747 | off |
| LLM legal terms appended to the question (qwen-2.5-7b, 40 questions) | 0.675 vs 0.812 | off |
| Same with gpt-4.1-mini | 0.713 vs 0.812 | off |
| LLM terms + deterministic rules combined | 0.821 vs 0.812 | not worth the extra call |
| LLM reranker over the top-30, pool hydrated | qwen-2.5-7b 0.738 vs 0.736; gpt-4.1-mini 0.773 vs 0.765 | `RERANK_PROVIDER=none` |
| gpt-4.1-mini as the generator | coverage 0.700 vs 0.917, abstention 0.800 vs 1.000, p50 6.7 s vs 10.8 s | keep the reasoning model |
| Dual query (raw question + expanded query), cap 3 | 0.744 vs 0.752 | off |
| Same with cap 5 per article | 0.711 vs 0.721 | off |
| HyDE (hypothetical legal answer as the query, 40 questions) | 0.617 vs 0.787; combined with the question 0.783 | off |

The rewrite experiments all fail the same way: replacing the question drops
the signal the dense leg was built on, and adding legal vocabulary on top of
the deterministic rules does not pay for the extra call. The generator result
is the latency/quality trade-off: the fast model is 4 s faster per question and
loses 20 points of citation coverage.
### Where the remaining recall sits

Measured on the 110 answerable questions with the dense leg:

| Granularity | recall@10 | Questions fully retrieved |
| --- | ---: | ---: |
| device | 0.771 | 67% |
| article | 0.817 | 75% |
| lexical only (Postgres FTS, idf coverage) | 0.423 | — |
| lexical, article level | 0.477 | — |

The correct article is missing from the top-10 for 25% of the questions,
while the "right article, wrong device" case is only 8% of them. So the
binding constraint is retrieval/representation, not the article dedupe;
that is why every ranking-side change (two rerankers, caps, dual query,
HyDE) measured neutral or worse.

### The evaluation set is narrow

The 110 answerable questions share only **16 distinct gold devices**: they
are paraphrases of a handful of scenarios, and all 16 devices exist in the
corpus. So "67% fully retrieved" means "found the right one of sixteen
targets", not "handles domestic-violence law". It is a regression signal,
not a SOTA measure; a blind set with distinct targets per question is still
missing, and the 20-question set was used to author the query rules.
### Provider budget

The live measurements need OpenRouter for both embeddings and generation.
When the key hits its credit limit every call returns 403, the pipeline
abstains on every question, and a run would publish ~0.2 recall as if it
were a measurement. `scripts/benchmark_production.py` now probes one
embedding and one chat completion first and exits with status 2 instead of
writing a report.
### Known deviations (audited, not fixed)

- `get_current_version_id` keeps the `vigente`/`alterado` filter when
  `data_fato` is supplied, so an unambiguous explicit citation of an article
  that was later revoked abstains instead of returning the version in force
  on that date.
- Versioned Qdrant payloads are not updated when `src/ingest/diff.py` closes
  a version, so a closed device keeps its old `vigencia_fim` until reindexed.
- `expand_to_article` needs the article row at the *same* `norm_version_id`;
  about 13% of leaf rows have no such row, so their context expansion
  degrades to the leaf and logs `incomplete_context`.