# 02 — Arquitetura e stack local

## 1. Visão geral

```text
                         +---------------------------+
                         |  UI (chat)                |
                         |  Next.js ou Streamlit     |
                         +-------------+-------------+
                                       |
                                       v
                         +---------------------------+
                         |  API (FastAPI)            |
                         |  /chat  /health  /sources |
                         +------+------+------+------+
                                |      |      |
              +-----------------+      |      +------------------+
              |                        |                         |
              v                        v                         v
   +---------------------+   +---------------------+   +---------------------+
   | Roteador de risco   |   | Orquestrador RAG    |   | Verificador de      |
   | (regex + regras)    |   | (subperguntas,      |   | citações            |
   | 190/180 antes do RAG|   |  busca, rerank)     |   | (IDs + suporte)     |
   +---------------------+   +----------+----------+   +----------+----------+
                                        |                         |
                     +------------------+-----------+             |
                     |                              |             |
                     v                              v             v
          +---------------------+        +---------------------+  |
          | PostgreSQL 17       |        | Qdrant (alvo)       |  |
          | - metadados         |        | - multivector       |  |
          | - versões           |        | - BM25 esparso      |  |
          | - full-text (FTS)   |        | - MaxSim            |  |
          | - pgvector (opc.)   |        +---------------------+  |
          +---------------------+                                 |
                     ^                                            |
                     |                                            |
          +----------+-----------+                                |
          | Pipeline de ingestão |                                |
          | download -> parse -> |                                |
          | chunk -> embed       |                                |
          +----------+-----------+                                |
                     ^                                            |
                     |                                            |
          +----------+-----------+                                |
          | Fontes oficiais      |                                |
          | Planalto, LexML,     |                                |
          | STJ, STF, CNJ        |                                |
          +----------------------+                                |
                                                                  |
          +-------------------------------------------------------+
          | LLM (local ou API com retenção zero)                   |
          +-------------------------------------------------------+
```

## 2. Componentes

| Componente     | Responsabilidade                                                     | Tecnologia sugerida                     |
| -------------- | -------------------------------------------------------------------- | --------------------------------------- |
| Coletor        | Baixar e versionar HTML/PDF oficial                                  | Python + `requests` + `httpx`           |
| Parser legal   | Transformar HTML em árvore de dispositivos                           | `lxml`/`BeautifulSoup` + parser próprio |
| Normalizador   | Corrigir encoding, remover riscado do índice, normalizar citações    | Python + `unidecode`                    |
| Store          | Fonte da verdade: normas, versões, dispositivos, relações, avaliação | PostgreSQL 17                           |
| Vetorizador    | Gerar multivector (alvo) ou vetor denso (fallback)                   | `sentence-transformers`                 |
| Índice lexical | BM25 esparso no Qdrant ou FTS no Postgres                            | Qdrant sparse / PostgreSQL FTS          |
| Recuperador    | Busca híbrida, filtros de vigência; RRF no fallback                  | Python + Qdrant/Postgres                |
| Reranker       | MaxSim no Qdrant (alvo) ou pplx/Qwen3 (fallback)                     | `pplx-embed-v2-late` / `Qwen3-Reranker` |
| Gerador        | Produzir resposta estruturada com IDs                                | LLM local ou API                        |
| Verificador    | Rejeitar ID inexistente/não recuperado e afirmação sem suporte       | Regras + LLM juiz                       |
| UI             | Chat, cards de citação, botões de emergência                         | Streamlit (MVP) ou Next.js              |
| Avaliação      | Medir recall, precisão de citação, abstenção                         | Script Python + JSONL                   |

## 3. Stack recomendada para o protótipo

| Camada           | Escolha                                      | Motivo                                             |
| ---------------- | -------------------------------------------- | -------------------------------------------------- |
| Linguagem        | Python 3.12                                  | Ecossistema de NLP e parsing                       |
| API              | FastAPI                                      | Leve, tipada, rápida de subir                      |
| Banco relacional | PostgreSQL 17 + `pgvector`                   | Metadados, versões, citações, FTS e fallback denso |
| Índice vetorial  | Qdrant local (v1.15.3)                       | Multivector/MaxSim do pplx late e BM25 esparso     |
| Indexador (alvo) | `pplx-embed-v2-late-9b`                      | Indexa com 9B e consulta com 0.6B no mesmo espaço  |
| Consulta (alvo)  | `pplx-embed-v2-late-0.6b`                    | Codificação de pergunta barata e local             |
| Fallback sem GPU | `harrier-oss-v1-0.6b` + rerank pplx 0.6B     | MVP viável em CPU/GPU modesta                      |
| LLM              | Local (Ollama/vLLM) ou API com retenção zero | Privacidade das perguntas                          |
| UI               | Streamlit                                    | Protótipo em horas, não dias                       |
| Infra local      | Docker Compose                               | Reprodutibilidade                                  |

### Caminho-alvo (com GPU)

O desenho combinado é assimétrico:

```text
Indexação:  pplx-embed-v2-late-9b -> multivector no Qdrant (MaxSim)
Candidatos: BM25 esparso no Qdrant (top 100 por subpergunta)
Consulta:   pplx-embed-v2-late-0.6b -> mesmo espaço vetorial
```

Por que:

- o 9B indexa com mais qualidade e o 0.6B consulta com latência baixa;
- o Qdrant faz MaxSim nativo, sem trazer todos os vetores para o Python;
- o Postgres continua como fonte da verdade de normas, versões, citações e auditoria;
- o Corpus inicial é pequeno, então o custo de indexação com 9B é aceitável.

Requisitos: GPU com memória suficiente (33,6 GB em F32; ~17 GB em FP16 + overhead; 24 GB é borderline, 48 GB é confortável) e Qdrant no stack.

### Fallback sem GPU

Se não houver GPU:

```text
Indexação:  harrier-oss-v1-0.6b -> pgvector (denso)
Consulta:   harrier-oss-v1-0.6b -> pgvector + FTS
Rerank:     pplx-embed-v2-late-0.6b sobre o top 50 (opcional)
```

Esse caminho é uma contingência para o protótipo rodar em qualquer máquina. Ele **não** substitui o desenho-alvo: perde o índice multivector do 9B e usa outro espaço vetorial na primeira etapa. O Harrier entra como fallback, não como escolha principal.

| Critério        | Caminho-alvo (9B/0.6B) | Fallback (Harrier + 0.6B)    |
| --------------- | ---------------------- | ---------------------------- |
| Qualidade       | Maior                  | Boa, mas abaixo do 9B        |
| GPU             | Necessária             | Opcional                     |
| Armazenamento   | Multivector por token  | Vetor denso por chunk        |
| Complexidade    | Qdrant + MaxSim        | Postgres + pgvector + rerank |
| Uso recomendado | Núcleo e produção      | Demo local e contingência    |

O Qdrant suporta vetores nomeados, esparsos com BM25 e multivector com `max_sim` (a partir da v1.10). Ele não substitui o Postgres como fonte da verdade: versões, citações e trilha de auditoria continuam no banco relacional.

## 4. Docker Compose local

```yaml
services:
  db:
    image: pgvector/pgvector:pg17
    environment:
      POSTGRES_USER: app
      POSTGRES_PASSWORD: app
      POSTGRES_DB: violencia
    ports:
      - "5432:5432"
    volumes:
      - pgdata:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U app -d violencia"]
      interval: 5s
      timeout: 3s
      retries: 10

  qdrant:
    image: qdrant/qdrant:v1.15.3
    ports:
      - "6333:6333"
      - "6334:6334"
    volumes:
      - qdrant_data:/qdrant/storage

volumes:
  pgdata:
  qdrant_data:
```

Subir o caminho-alvo (Postgres + Qdrant):

```bash
docker compose up -d
```

Subir só o fallback (Postgres, sem GPU):

```bash
docker compose up -d db
```

## 5. Estrutura de pastas sugerida

```text
.
├── docker-compose.yml
├── pyproject.toml
├── .env.example
├── data/
│   ├── raw/                 # snapshots HTML/PDF com hash
│   ├── processed/           # JSONL de dispositivos
│   └── eval/                # perguntas e rótulos
├── src/
│   ├── ingest/
│   │   ├── fetch.py
│   │   ├── parse_planalto.py
│   │   ├── parse_cnj.py
│   │   ├── parse_sumulas.py
│   │   └── normalize.py
│   ├── index/
│   │   ├── chunk.py
│   │   ├── embed.py
│   │   └── load_db.py
│   ├── retrieve/
│   │   ├── hybrid.py
│   │   ├── rerank.py
│   │   ├── expand.py
│   │   └── citations.py
│   ├── generate/
│   │   ├── prompt.py
│   │   ├── llm.py
│   │   └── verify.py
│   ├── api/
│   │   ├── main.py
│   │   └── schemas.py
│   └── eval/
│       ├── run.py
│       └── metrics.py
├── web/                     # Streamlit ou Next.js
├── docs/
└── tests/
```

A árvore completa, com todos os arquivos por task, está em [`10-plano-implementacao.md` §4](10-plano-implementacao.md#4-estrutura-de-arquivos).

## 6. Fluxo de uma pergunta

```text
1. Recebe mensagem
2. Roteador de risco
   ├─ risco imediato -> resposta fixa + 190/180 -> fim
   ├─ citação explícita -> busca direta por ID -> contexto
   └─ pergunta comum -> segue
3. Entendimento da consulta
   ├─ extrai fatos: relação, tipo de violência, urgência, data
   ├─ reescreve em linguagem jurídica
   └─ divide em até 3 subperguntas
4. Para cada subpergunta, em paralelo:
   ├─ alvo: BM25 esparso no Qdrant (top 100)
   ├─ fallback: denso no pgvector + FTS (top 50)
   └─ união (máx. 150 candidatos)
5. MaxSim / rerank
   ├─ alvo: MaxSim no Qdrant
   ├─ fallback: pplx late 0.6B ou Qwen3
   └─ top 10
6. Deduplicação e expansão
   ├─ deduplica por artigo (melhor score)
   ├─ sobe para o artigo/caput
   └─ segue remissões do grafo (quando existir)
7. Montagem do contexto
   ├─ ordem: constituição/lei > súmula/tese > ato CNJ > doutrina
   ├─ inclui texto literal + explicação simples
   └─ inclui IDs e metadados de vigência
8. Geração
   └─ LLM devolve JSON com resposta + lista de {device_id, afirmacao}
9. Verificação
   ├─ todo ID existe?
   ├─ todo ID está no conjunto recuperado?
   ├─ toda afirmação jurídica tem ID?
   └─ se falhar: regenera 1x ou abstém
10. Renderização
    ├─ resposta
    ├─ cards de citação com texto literal e link
    ├─ próximos passos
    └─ aviso + data de atualização
```

## 7. Contratos de API

### `POST /chat`

```json
{
  "session_id": "uuid",
  "message": "Ele me agrediu e continua me ameaçando por mensagem. Ainda dá tempo de denunciar?",
  "facts": {
    "data_fato": "2026-10-01",
    "uf": "SP"
  }
}
```

Resposta:

```json
{
  "resposta": "Sim. A lesão corporal em contexto doméstico é crime de ação pública incondicionada, então a denúncia não depende da sua representação. Quanto aos crimes que dependem de queixa ou representação, o prazo é de 12 meses contados de quando você soube quem é o autor. Como o fato é de 01/10/2026, aplica-se a regra atual. Você também pode pedir medida protetiva sem boletim de ocorrência, e ela pode proibir contato por qualquer meio.",
  "citacoes": [
    {
      "norm_version_id": 1,
      "device_id": "stj-sum-542",
      "citacao": "Súmula nº 542 do STJ",
      "texto": "A ação penal relativa ao crime de lesão corporal resultante de violência doméstica contra a mulher é pública incondicionada.",
      "fonte_url": "https://scon.stj.jus.br/SCON/sumstj/"
    },
    {
      "norm_version_id": 1,
      "device_id": "lmp/art16-a",
      "citacao": "Lei nº 11.340/2006, art. 16-A",
      "texto": "Nos crimes praticados no âmbito de violência doméstica e familiar contra a mulher, a ofendida decai do direito de queixa ou de representação se não o exerce no prazo de 12 (doze) meses...",
      "fonte_url": "https://www.planalto.gov.br/ccivil_03/_ato2004-2006/2006/lei/l11340.htm"
    },
    {
      "norm_version_id": 1,
      "device_id": "lmp/art19/par5",
      "citacao": "Lei nº 11.340/2006, art. 19, § 5º",
      "texto": "As medidas protetivas de urgência serão concedidas independentemente da tipificação penal da violência, do ajuizamento de ação penal ou cível, da existência de inquérito policial ou do registro de boletim de ocorrência.",
      "fonte_url": "https://www.planalto.gov.br/ccivil_03/_ato2004-2006/2006/lei/l11340.htm"
    },
    {
      "norm_version_id": 1,
      "device_id": "lmp/art22/cpt/inc3/ali-b",
      "citacao": "Lei nº 11.340/2006, art. 22, III, \"b\"",
      "texto": "contato com a ofendida, seus familiares e testemunhas por qualquer meio de comunicação;",
      "fonte_url": "https://www.planalto.gov.br/ccivil_03/_ato2004-2006/2006/lei/l11340.htm"
    }
  ],
  "proximos_passos": [
    "Registrar boletim de ocorrência na delegacia mais próxima ou na DEAM.",
    "Pedir medida protetiva de urgência; ela não depende de boletim de ocorrência.",
    "Procurar a Defensoria Pública para acompanhamento."
  ],
  "emergencia": false,
  "nivel_confianca": "alto",
  "data_atualizacao_base": "2026-11-05"
}
```

### `GET /health`

Retorna status do banco, versão do índice e data da última ingestão.

### `GET /sources/{device_id}?version={norm_version_id}`

Retorna metadados completos, texto literal, contexto, vigência e URL da versão solicitada. Aceitar também `?date=YYYY-MM-DD` para resolver a versão vigente na data.

## 8. Observabilidade e auditoria

Registrar por requisição:

- `request_id` e `session_id` (sem PII);
- classificação de risco;
- subperguntas geradas;
- IDs recuperados e IDs usados;
- scores de busca e rerank;
- modelo, versão e latência de cada etapa;
- resultado do verificador;
- data de atualização da base.

Não registrar, por padrão:

- texto integral da pergunta;
- nome, endereço, telefone ou qualquer dado pessoal;
- conteúdo de conversas anteriores sem consentimento.

Para depuração, usar amostras anonimizadas e retenção curta.

## 9. Segurança

- **Rede local:** Postgres e Qdrant não expostos publicamente.
- **Segredos:** `.env` fora do repositório; nunca commitar chaves.
- **Criptografia:** volume criptografado no host; TLS se houver acesso remoto.
- **Acesso:** usuário de banco com permissões mínimas; sem superusuário na aplicação.
- **Backup:** dump diário local; testar restauração.
- **Dependências:** versões fixadas; `pip-audit`/`npm audit` no CI.
- **Conteúdo:** sanitizar HTML recuperado; nunca executar scripts de páginas coletadas.

## 10. Evolução para produção

1. Trocar Streamlit por Next.js com autenticação e acessibilidade.
2. Mover Postgres para instância gerenciada com backup e réplica.
3. Manter o Qdrant no caminho-alvo; o fallback sem GPU usa pgvector.
4. Colocar o LLM atrás de um gateway com timeout, fallback e orçamento.
5. Adicionar fila para ingestão e reindexação incremental.
6. Monitorar recall e citação em produção com amostragem revisada.
7. Formalizar contrato de retenção zero com qualquer API externa.
8. Auditar o sistema com apoio jurídico e de segurança antes do lançamento.
