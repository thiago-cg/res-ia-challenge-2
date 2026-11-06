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
| Caminho fallback (Harrier + pgvector + FTS/RRF) | Implementado e coberto por testes unitários. Não foi executado de ponta a ponta neste ambiente. |
| Caminho alvo (pplx 9B/0.6B + Qdrant) | Código presente, atrás de `RETRIEVAL_PATH=target`. O app padrão não monta o searcher Qdrant; é preciso injetar um pipeline. Sem GPU/safetensors validados. |
| Ingestão | `src.ingest.run` **apenas baixa** os arquivos brutos e calcula hash. Não há CLI de parsing/carga neste branch. |
| Índice | `src.index.run --path fallback` existe, mas exige `EMBEDDING_MODEL_REVISION` pinado e o extra `ml`. |
| Avaliação | Harness e 150 perguntas existem. **Métricas PENDENTES**: nenhum recall, citação, groundedness ou latência foi medido contra Postgres/Qdrant ao vivo. O adaptador real `build_eval_pipeline` ainda não existe; a CLI falha com mensagem clara. |
| Revisão jurídica | **PENDENTE**. Nenhuma advogada, defensora ou pessoa da rede de atendimento revisou prompt, textos ou respostas. Não há parecer. |
| Modelos locais | Os artefatos locais são **GGUF** (llama.cpp). O caminho alvo precisa de **safetensors**. GGUF levanta `ModelFormatError`; o fallback é o padrão. |
| Docker/Postgres/Qdrant | `docker-compose.yml` e CI existem, mas **não há Docker, Postgres ou Qdrant ao vivo** no ambiente em que este status foi escrito. Testes de integração não foram executados aqui. |
| Observabilidade | Módulos de log estruturado e middleware existem e têm testes, mas `create_app` ainda **não instala** os middlewares. Não há garantia de `X-Request-ID` na API hoje. |
| LLM | Padrão `LLM_PROVIDER=mock`. Os provedores `local`/`api` existem no código, mas `llm_base_url`/`llm_api_key` não estão em `Settings` nem no `.env.example`; não são configuráveis de ponta a ponta. |

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
- Rede apenas para a ingestão das fontes oficiais.

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

O padrão `LLM_PROVIDER=mock` não precisa de chave. Não há campos de URL/chave de
LLM em `Settings`; para esta versão, use `mock`.

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

### 5. Ingestão (download dos textos oficiais)

```powershell
uv run python -m src.ingest.run --priority P0
```

Opções reais da CLI: `--source <id>`, `--priority P0|P1` ou `--all`
(mutuamente exclusivas), além de `--manifest`, `--dest-dir`, `--timeout` e
`--retries`. Os arquivos vão para `data/raw/` com sidecar `.meta.json` e hash
SHA-256; a execução é idempotente.

**Importante:** essa CLI **só baixa**. Ela não parseia nem carrega o Postgres.
Não há CLI de carga neste branch.

### 6. Carga do corpus (sem CLI dedicada)

Depois do download, parseie e carregue com as funções existentes:

```powershell
uv run python -c @"
import psycopg
from src.config import get_settings
from src.index.load_db import load_parse_result
from src.ingest.fetch import fetch_source, load_sources
from src.ingest.run import parse_downloaded_source

settings = get_settings()
with psycopg.connect(settings.database_url) as conn:
    for source in load_sources("data/sources.yaml"):
        if not source.enabled:
            continue
        fetched = fetch_source(source, "data/raw")
        result = parse_downloaded_source(source, fetched.path)
        report = load_parse_result(conn, result)
        conn.commit()
        print(source.id, report.devices_loaded, report.versions_loaded)
"@
```

Esse bloco é o caminho suportado hoje; ele não substitui uma CLI de ingestão
completa e pode precisar de ajuste para fontes cujo parser exija tratamento
específico.

### 7. Índice fallback

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

### 8. API e interface

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

### 9. Testes e qualidade

```powershell
uv run pytest -m "not integration"
uv run pytest -m integration
uv run ruff check .
uv run ruff format --check .
uv run mypy src
```

`pytest -m integration` exige Postgres/Qdrant vivos e não foi executado no
ambiente deste status. O CI define os serviços e aplica as migrações antes.

## Variáveis de ambiente

Todas as chaves de `.env.example`. O default entre parênteses é o usado pelo
código quando a variável não existe.

| Variável | Default | Para que serve |
| --- | --- | --- |
| `RETRIEVAL_PATH` | `fallback` | `fallback` (pgvector/FTS) ou `target` (Qdrant/9B). O alvo ainda exige injeção de searcher. |
| `EMBEDDING_PROVIDER` | `harrier` | `harrier` no fallback; `pplx` para os modelos pplx. |
| `EMBEDDING_MODEL_REVISION` | vazio | Commit/tag do modelo. **Obrigatório para indexar**; vazio ou `main` levanta erro. |
| `LLM_PROVIDER` | `mock` | `mock`, `local` ou `api`. Só `mock` é configurável de ponta a ponta neste branch. |
| `MAX_DEVICES` | `10` | Máximo de dispositivos no contexto/resposta. |
| `MAX_CONTEXT_TOKENS` | `6000` | Orçamento de tokens do contexto. |
| `MAX_SUBQUESTIONS` | `3` | Máximo de subperguntas (contrato limita a 3). |
| `MAX_AGENT_LOOPS` | `3` | Limite de loops do agente; presente na config. |
| `DATABASE_URL` | `postgresql://app:app@localhost:5432/violencia` | Postgres, fonte da verdade. |
| `QDRANT_URL` | `http://localhost:6333` | Qdrant do caminho alvo e do health check. |
| `PPX_9B_MODEL_PATH` | vazio | Diretório **safetensors** do pplx 9B (indexação alvo). Valor terminado em `.gguf` é rejeitado. |
| `PPX_06B_MODEL_PATH` | vazio | Diretório **safetensors** do pplx 0.6B (consulta alvo/rerank). Valor terminado em `.gguf` é rejeitado. |
| `HARRIER_MODEL_PATH` | vazio | Diretório **safetensors** do Harrier; vazio usa `microsoft/harrier-oss-v1-0.6b`. Valor terminado em `.gguf` é rejeitado. |
| `LLM_MODEL` | vazio | Nome do modelo do provedor LLM; com `mock`, vira `mock`. |
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

Neste branch, o comando falha com mensagem clara porque
`src.api.main.build_eval_pipeline` ainda não existe. O harness só roda com um
pipeline injetado em teste. **Nenhuma métrica foi produzida.**

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
  padrão é `mock`.
- **Emergência:** o bloco com 190/180/100/197 é avaliado antes do RAG e não toca
  banco, busca ou LLM.
- **UI:** a barra lateral repete o aviso de não substituição e orienta a não
  informar nome, CPF, endereço, telefone ou documentos.
- **Risco conhecido:** os middlewares de correlação e headers de segurança
  existem e são testados, mas `create_app` ainda não os instala; não trate
  `X-Request-ID` como disponível na API até essa fiação ser feita.

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

- Não há um comando único de ingestão ponta a ponta: a CLI baixa, mas parsing e
  carga precisam do bloco Python da seção 6.
- O caminho alvo (9B/Qdrant) não está operacional com os artefatos locais; os
  GGUF não servem e não há safetensors validados.
- O caminho alvo de recuperação não é montado pelo `create_app` padrão; exige
  injeção de pipeline/searcher.
- O adaptador de avaliação real (`build_eval_pipeline`) não existe; as métricas
  seguem pendentes.
- LLM `local`/`api` sem campos de URL/chave em `Settings`/`.env.example`.
- Middlewares de request ID/segurança não estão ligados em `create_app`.
- Nenhuma revisão jurídica humana; nenhum gate G4/G6.

Próximos passos, na ordem:

1. Fechar a fiação dos middlewares e expor `X-Request-ID` com testes de API.
2. Criar a CLI/etapa de parsing + carga e um smoke de ingestão → índice.
3. Conseguir checkpoints safetensors e executar o smoke 9B/0.6B (G5).
4. Implementar `build_eval_pipeline` e rodar as 150 perguntas com Postgres/Qdrant.
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
