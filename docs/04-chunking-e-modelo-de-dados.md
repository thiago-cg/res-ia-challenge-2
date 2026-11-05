# 04 — Chunking e modelo de dados

## 1. A unidade é o dispositivo, não o token

Leis e atos normativos têm estrutura. O chunker deve seguir essa estrutura, não cortar a cada 500 tokens.

A hierarquia segue a LC nº 95/1998:

```text
norma
└── título
    └── capítulo
        └── seção
            └── artigo
                ├── caput
                ├── parágrafo (§)
                │   ├── inciso
                │   │   ├── alínea
                │   │   │   └── item
                │   │   └── ...
                │   └── ...
                └── ...
```

### Por que isso importa

O sentido é herdado do nível de cima. Um exemplo da Lei Maria da Penha:

```text
Art. 22. Constatada a prática de violência doméstica e familiar contra a mulher,
o juiz poderá aplicar, de imediato, ao agressor, em conjunto ou separadamente,
as seguintes medidas protetivas de urgência, entre outras:
...
III - proibição de determinadas condutas, entre as quais:
...
b) contato com a ofendida, seus familiares e testemunhas por qualquer meio
de comunicação;
```

A alínea "b", isolada, fala em "contato (...) por qualquer meio de comunicação". A palavra "proibição" está no inciso III; "medida protetiva de urgência" está no caput. Um chunk por tamanho pode entregar ao LLM um trecho que parece dizer o contrário da lei.

Por isso, cada unidade indexada carrega:

1. o texto literal do dispositivo;
2. a cadeia completa (caput → inciso → alínea);
3. o caminho estrutural (título, capítulo, seção);
4. a citação canônica;
5. a vigência.

Esse contexto é montado de forma **determinística**, a partir da árvore. Não é gerado por LLM.

## 2. Duas granularidades

| Grânulo           | ID                         | Uso                 | Conteúdo                                     |
| ----------------- | -------------------------- | ------------------- | -------------------------------------------- |
| Dispositivo-folha | `lmp/art22/cpt/inc3/ali-b` | Precisão da busca   | Texto do dispositivo + cabeçalho de contexto |
| Artigo inteiro    | `lmp/art22`                | Contexto para o LLM | Caput + todos os incisos/alíneas + cabeçalho |

A busca encontra a folha; o sistema entrega o artigo completo ao modelo. Os dois grânulos ficam ligados por `artigo_id`.

Para dispositivos muito longos (caput com muitos incisos), o artigo pode ser dividido em "blocos de artigo" com o mesmo `artigo_id`, mas o padrão é um artigo por chunk de contexto.

## 3. ID canônico

Formato local:

```text
{norma}/{artigo}[/{nivel}...]
```

Exemplos:

```text
lmp/art22
lmp/art22/cpt
lmp/art22/cpt/inc3
lmp/art22/cpt/inc3/ali-b
cp/art129/par3
cpp/art38/par2
cnj-rc-5-2020/art4
stj-sum-542
stf-adi-4424
```

Regras:

- `norma`: slug estável (`lmp`, `cp`, `cpp`, `cf`, `cnj-rc-5-2020`).
- `artigo`: `art` + número, preservando hífen (`art24-A` → `art24-a`).
- `nivel`: `cpt` (caput), `par1` (parágrafo 1º), `par-unico`, `inc3`, `ali-b`, `item-1`.
- Minúsculas, sem acento, sem espaço.
- O ID não muda quando o texto muda; a versão é outro campo.

### Mapeamento LexML

Guardar a URN externa em `norms.urn_lexml`:

```text
urn:lex:br:federal:lei:2006-08-07;11340
```

Para dispositivos, o LexML usa fragmentos observados como:

```text
urn:lex:br:federal:lei:2006-08-07;11340!art22_cpt_inc3
```

O formato exato para alínea/item deve ser validado no resolvedor antes de virar chave. O ID local é a chave primária; a URN é um atributo externo.

## 4. Cabeçalho de contexto determinístico

Para cada dispositivo, montar:

```text
Lei nº 11.340/2006 (Lei Maria da Penha)
Título III — Das Medidas Protetivas de Urgência
Capítulo II — Das Medidas Protetivas de Urgência que Obrigam o Agressor
Art. 22, caput, inciso III, alínea "b"
```

O cabeçalho é usado no texto enviado ao embedder e ao LLM, mas **não** entra no `texto_literal` nem na citação. A citação é um campo separado, também determinístico.

## 5. Versionamento

### O problema do texto riscado

O texto compilado do Planalto mantém a redação revogada riscada ao lado da nova. Uma conversão ingênua de HTML para texto junta as duas. No art. 24-A, por exemplo, o modelo pode ver duas penas porque a Lei nº 14.994/2024 alterou a detenção para reclusão.

### Regras

1. Remover do índice o texto riscado (`<s>`, `<strike>`, `~~...~~`).
2. Guardar o texto anterior em `texto_anterior`.
3. Guardar o ato que deu a nova redação em `redacao_dada_por`.
4. Guardar a data de início da vigência em `vigencia_inicio`.
5. Fechar a versão anterior com `vigencia_fim`.
6. Nunca sobrescrever a linha: criar nova versão e apontar `norm_version_id`.
7. `devices` guarda apenas identidade/estrutura; todas as versões (inclusive a corrente) ficam em `device_versions`; `devices_current` expõe a vigente.

### Datas

- `vigencia_inicio`: data em que a redação passou a valer.
- `vigencia_fim`: data em que deixou de valer (NULL se vigente).
- `data_fato`: data informada pela usuária ou extraída da conversa.
- Consulta padrão: `vigencia_inicio <= data_fato AND (vigencia_fim IS NULL OR vigencia_fim >= data_fato)`.
- Sem data do fato: usar a versão vigente hoje.
- `norm_versions` é o **evento de alteração/proveniência** (norma, data, fonte, hash), não um snapshot da norma inteira.
- `device_versions` é o texto de um dispositivo entre `vigencia_inicio` e `vigencia_fim`; o filtro por data usa essas colunas, não o `norm_version_id` mais recente.
- Um dispositivo não alterado mantém sua linha em `device_versions`; não é preciso criar uma linha nova para cada evento da norma.

### Status

| Status      | Significado                                     |
| ----------- | ----------------------------------------------- |
| `vigente`   | Texto atual                                     |
| `alterado`  | Dispositivo com nova redação, mas ainda vigente |
| `revogado`  | Sem vigência                                    |
| `cancelado` | Súmula cancelada                                |
| `superado`  | Entendimento superado                           |

## 6. Metadados por chunk

| Campo                      | Exemplo                                                                                   |
| -------------------------- | ----------------------------------------------------------------------------------------- |
| `id`                       | `lmp/art22/cpt/inc3/ali-b`                                                                |
| `norm_id`                  | `lmp`                                                                                     |
| `norm_version_id`          | `42`                                                                                      |
| `parent_id`                | `lmp/art22/cpt/inc3`                                                                      |
| `artigo_id`                | `lmp/art22`                                                                               |
| `tipo`                     | `alinea`                                                                                  |
| `rotulo`                   | `alínea "b"`                                                                              |
| `texto_literal`            | `contato com a ofendida, seus familiares e testemunhas por qualquer meio de comunicação;` |
| `contexto`                 | caput + inciso + caminho                                                                  |
| `caminho`                  | `Título III > Capítulo II > Art. 22 > III > b`                                            |
| `citacao`                  | `Lei nº 11.340/2006 (Lei Maria da Penha), art. 22, caput, inciso III, alínea "b"`         |
| `vigencia_status`          | `vigente`                                                                                 |
| `redacao_dada_por`         | `texto original (2006)`                                                                   |
| `vigencia_inicio`          | `2006-09-22`                                                                              |
| `vigencia_fim`             | `NULL`                                                                                    |
| `fonte_url`                | URL do Planalto                                                                           |
| `content_hash`             | SHA-256 do texto + metadados                                                              |
| `remissoes`                | IDs citados/alterados                                                                     |
| `search_text`              | texto normalizado para busca                                                              |
| `embedding`                | vetor denso                                                                               |
| `embedding_model`          | `harrier-oss-v1-0.6b`                                                                     |
| `embedding_model_revision` | commit/revisão fixada do modelo                                                           |
| `embedding_text_hash`      | SHA-256 de `contexto + "\n" + texto_literal`                                              |
| `qdrant_point_id`          | `UUIDv5(device_id@norm_version_id)`                                                       |
| `indexed_at`               | timestamp da indexação                                                                    |

## 7. Enriquecimento no índice

A maior distância é de vocabulário. A usuária pergunta "ele pode ser proibido de me mandar mensagem?"; a lei fala em "proibição de contato com a ofendida".

Para cada dispositivo, gerar offline com LLM:

1. **Explicação em linguagem simples** (1–3 frases).
2. **5 a 10 perguntas** que uma vítima faria sobre ele (doc2query).

Indexar como vetores nomeados do mesmo ponto:

- `texto` — literal + contexto;
- `explicacao` — explicação simples;
- `perguntas` — cada pergunta como um vetor.

O texto literal continua intocado para a citação. Os pares pergunta → dispositivo servem depois como dados de treino para fine-tuning do embedder.

## 8. Schema SQL (PostgreSQL + pgvector)

```sql
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pg_trgm;
CREATE EXTENSION IF NOT EXISTS unaccent;

CREATE TABLE norms (
    id              text PRIMARY KEY,
    tipo            text NOT NULL,
    numero          text NOT NULL,
    ano             integer NOT NULL,
    apelido         text,
    ementa          text,
    urn_lexml       text UNIQUE,
    fonte_url       text NOT NULL,
    created_at      timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE norm_versions (
    id              bigserial PRIMARY KEY,
    norm_id         text NOT NULL REFERENCES norms(id),
    vigencia_inicio date NOT NULL,
    vigencia_fim    date,
    fonte_url       text NOT NULL,
    retrieved_at    timestamptz NOT NULL DEFAULT now(),
    content_hash    text NOT NULL,
    UNIQUE (norm_id, vigencia_inicio)
);

CREATE TABLE devices (
    id          text PRIMARY KEY,
    norm_id     text NOT NULL REFERENCES norms(id),
    parent_id   text REFERENCES devices(id),
    artigo_id   text NOT NULL,
    tipo        text NOT NULL CHECK (tipo IN (
                    'artigo', 'caput', 'paragrafo',
                    'inciso', 'alinea', 'item'
                )),
    rotulo      text NOT NULL,
    caminho     text NOT NULL,
    ordem       integer NOT NULL
);

CREATE TABLE device_questions (
    id              bigserial PRIMARY KEY,
    device_id       text NOT NULL,
    norm_version_id bigint NOT NULL,
    pergunta        text NOT NULL,
    embedding       vector(1024),
    embedding_model text,
    gerado_por      text,
    created_at      timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE device_relations (
    from_id   text NOT NULL REFERENCES devices(id) ON DELETE CASCADE,
    to_id     text NOT NULL REFERENCES devices(id) ON DELETE CASCADE,
    tipo      text NOT NULL CHECK (tipo IN (
                  'remissao', 'alteracao', 'interpreta',
                  'revoga', 'regulamenta'
              )),
    fonte     text,
    PRIMARY KEY (from_id, to_id, tipo)
);

CREATE TABLE ingest_runs (
    id              bigserial PRIMARY KEY,
    source_id       text NOT NULL,
    started_at      timestamptz NOT NULL DEFAULT now(),
    finished_at     timestamptz,
    status          text NOT NULL CHECK (status IN ('running', 'ok', 'error')),
    content_hash    text,
    devices_seen    integer,
    devices_changed integer,
    error           text
);

CREATE TABLE eval_questions (
    id                bigserial PRIMARY KEY,
    pergunta          text NOT NULL,
    resposta_esperada text,
    device_ids        text[] NOT NULL,
    categoria         text,
    criado_por        text,
    revisado_por      text,
    revisado_em       timestamptz
);

CREATE INDEX devices_norm_artigo_idx
    ON devices (norm_id, artigo_id);

CREATE INDEX devices_parent_idx
    ON devices (parent_id);

CREATE INDEX devices_rotulo_trgm_idx
    ON devices USING GIN (rotulo gin_trgm_ops);
```

### 8.1 Versões, identidade no Qdrant e hidratação

O schema acima separa **identidade** de **versão**: `devices` é a identidade estrutural estável; `device_versions` é a única fonte de texto, vigência e embedding. A view `devices_current` expõe a versão vigente.

```sql
CREATE TABLE device_versions (
    id                       bigserial PRIMARY KEY,
    device_id                text NOT NULL REFERENCES devices(id) ON DELETE CASCADE,
    norm_id                  text NOT NULL REFERENCES norms(id),
    norm_version_id          bigint NOT NULL REFERENCES norm_versions(id),
    texto_literal            text NOT NULL,
    texto_anterior           text,
    contexto                 text NOT NULL,
    citacao                  text NOT NULL,
    vigencia_status          text NOT NULL CHECK (vigencia_status IN (
                                 'vigente', 'alterado', 'revogado',
                                 'cancelado', 'superado'
                             )),
    redacao_dada_por         text,
    vigencia_inicio          date NOT NULL,
    vigencia_fim             date,
    fonte_url                text NOT NULL,
    content_hash             text NOT NULL,
    qdrant_point_id          uuid NOT NULL UNIQUE,
    embedding                vector(1024),
    embedding_model          text,
    embedding_model_revision text,
    embedding_text_hash      text,
    search_text              text NOT NULL,
    search_vector            tsvector GENERATED ALWAYS AS (
                                 to_tsvector('portuguese', search_text)
                             ) STORED,
    indexed_at               timestamptz,
    qdrant_collection        text,
    UNIQUE (device_id, norm_version_id),
    CHECK (vigencia_fim IS NULL OR vigencia_fim >= vigencia_inicio)
);

CREATE TABLE device_explanations (
    device_id       text NOT NULL,
    norm_version_id bigint NOT NULL,
    texto           text NOT NULL,
    gerado_por      text,
    revisado_por    text,
    revisado_em     timestamptz,
    PRIMARY KEY (device_id, norm_version_id),
    FOREIGN KEY (device_id, norm_version_id)
        REFERENCES device_versions(device_id, norm_version_id) ON DELETE CASCADE
);

CREATE INDEX device_versions_vigencia_idx
    ON device_versions (vigencia_inicio, vigencia_fim);

CREATE INDEX device_versions_norm_idx
    ON device_versions (norm_id, norm_version_id);

CREATE INDEX device_versions_search_idx
    ON device_versions USING GIN (search_vector);

CREATE INDEX device_versions_embedding_idx
    ON device_versions USING hnsw (embedding vector_cosine_ops);

ALTER TABLE device_questions
    ADD CONSTRAINT device_questions_version_fk
    FOREIGN KEY (device_id, norm_version_id)
    REFERENCES device_versions(device_id, norm_version_id) ON DELETE CASCADE;

CREATE VIEW devices_current AS
SELECT d.id AS device_id,
       d.norm_id,
       d.artigo_id,
       d.tipo,
       d.rotulo,
       d.caminho,
       dv.norm_version_id,
       dv.texto_literal,
       dv.contexto,
       dv.citacao,
       dv.vigencia_status,
       dv.vigencia_inicio,
       dv.vigencia_fim
FROM devices d
JOIN device_versions dv ON dv.device_id = d.id
WHERE dv.vigencia_status IN ('vigente', 'alterado')
  AND dv.vigencia_inicio <= CURRENT_DATE
  AND (dv.vigencia_fim IS NULL OR dv.vigencia_fim >= CURRENT_DATE);
```

Regras:

- `qdrant_point_id = UUIDv5(namespace, f"{device_id}@{norm_version_id}")`.
- O payload do Qdrant inclui `device_id`, `norm_version_id`, `artigo_id`, `norm_id`, `tipo`, `vigencia_status`, `vigencia_inicio`, `vigencia_fim`.
- `artigo_id` e `tipo` vêm de `devices` no momento do upsert; não duplicar no histórico.
- A consulta padrão filtra a versão vigente hoje; com data do fato, filtra `vigencia_inicio <= data_fato AND (vigencia_fim IS NULL OR vigencia_fim >= data_fato)`.
- `versao_em(norm_id, data)` retorna o evento (`norm_version_id`) ativo na data; `obter_dispositivo(device_id, data)` seleciona `device_versions` por `vigencia_inicio`/`vigencia_fim`. O `norm_version_id` é proveniência, não o seletor de texto.
- `embedding_text_hash = SHA-256(UTF-8(contexto + "\n" + texto_literal))`.
- Reindexação: criar a coleção `devices_v2`, validar e trocar o alias `devices_qdrant_current`.

Hidratação do contexto (Qdrant -> Postgres):

```sql
WITH requested AS (
    SELECT *
    FROM unnest(
        :device_ids::text[],
        :norm_version_ids::bigint[]
    ) AS r(device_id, norm_version_id)
)
SELECT r.device_id,
       r.norm_version_id,
       dv.texto_literal,
       dv.contexto,
       dv.citacao,
       dv.vigencia_status,
       dv.vigencia_inicio,
       dv.vigencia_fim,
       dv.fonte_url,
       de.texto AS explicacao
FROM requested r
JOIN device_versions dv
  ON dv.device_id = r.device_id
 AND dv.norm_version_id = r.norm_version_id
JOIN norms n ON n.id = dv.norm_id
LEFT JOIN device_explanations de
       ON de.device_id = dv.device_id
      AND de.norm_version_id = dv.norm_version_id;
```

### Notas de schema

- `vector(1024)` assume o fallback Harrier-OSS-v1-0.6B. `devices` não guarda embedding; `device_versions.embedding` é o vetor do fallback, e no alvo o multivector fica no Qdrant.
- O pplx late não é um vetor único. No alvo, ele vai para uma coleção multivector no Qdrant; no fallback, atua como reranker em memória.
- `device_versions` é a fonte única de texto, vigência e embedding; `devices` guarda identidade/estrutura; `devices_current` expõe a versão vigente.
- A tabela de metadados por chunk é uma visão lógica: texto, vigência e embedding vivem em `device_versions`.
- `search_text` é populado pela aplicação com texto normalizado: minúsculas, sem acento, citações expandidas (`art. 7º` → `artigo 7`).
- `texto_anterior` guarda a redação riscada; não é indexado.
- `citacao` é gerada no ingestion a partir de `norms` + `rotulo` + `caminho`; não é escrita pelo LLM.
- `device_explanations` guarda a explicação em texto; o vetor de explicação pode ser derivado dela.

## 9. Resolvedor de citação

O LLM devolve apenas `device_id` + `afirmacao`. A versão é anexada pela camada de recuperação, conforme `data_fato`/filtro de vigência; o modelo não escolhe `norm_version_id`. O resolvedor busca no banco e monta a citação:

```python
def resolve_citation(device_id: str, retrieved_version_id: int) -> Citation:
    # retrieved_version_id vem do candidato recuperado, nunca do LLM.
    row = db.get_device_version(device_id, retrieved_version_id)
    return Citation(
        device_id=row.device_id,
        norm_version_id=row.norm_version_id,
        citacao=row.citacao,
        texto=row.texto_literal,
        contexto=row.contexto,
        vigencia=row.vigencia_status,
        fonte_url=row.fonte_url,
    )
```

Exemplos de saída:

| device_id                  | citação                                                                         |
| -------------------------- | ------------------------------------------------------------------------------- |
| `lmp/art22/cpt/inc3/ali-b` | Lei nº 11.340/2006 (Lei Maria da Penha), art. 22, caput, inciso III, alínea "b" |
| `lmp/art19/par1`           | Lei nº 11.340/2006, art. 19, § 1º                                               |
| `stj-sum-542`              | Súmula nº 542 do STJ                                                            |
| `stj-sum-600`              | Súmula nº 600 do STJ                                                            |
| `cnj-rc-5-2020/art4`       | Resolução Conjunta CNJ/CNMP nº 5/2020, art. 4º                                  |
| `stf-adi-4424`             | STF, ADI nº 4.424                                                               |

## 10. Pseudocódigo do parser

```python
def build_device(node, parent, norm, path):
    device = Device(
        id=make_id(norm.slug, node.artigo, node.path),
        norm_id=norm.id,
        parent_id=parent.id if parent else None,
        artigo_id=make_id(norm.slug, node.artigo),
        tipo=node.tipo,
        rotulo=node.rotulo,
        texto_literal=node.texto_vigente,
        texto_anterior=node.texto_riscado,
        contexto=render_context(norm, path, node),
        caminho=render_path(path),
        citacao=render_citation(norm, path, node),
        vigencia_status=node.status,
        redacao_dada_por=node.redacao_dada_por,
        vigencia_inicio=node.vigencia_inicio,
        vigencia_fim=node.vigencia_fim,
        fonte_url=norm.fonte_url,
        content_hash=sha256(node.texto_vigente + metadata),
    )
    for child in node.children:
        build_device(child, device, norm, path + [node])
    return device
```

## 11. Casos de borda

| Caso                               | Tratamento                                                     |
| ---------------------------------- | -------------------------------------------------------------- |
| `Art. 24-A`                        | Preservar o hífen no ID (`art24-a`); não confundir com inciso  |
| `§ 1º` / `§1º` / `Parágrafo único` | Normalizar para `par1` / `par-unico`                           |
| `III -` / `III –`                  | Normalizar para `inc3`                                         |
| `b)` / `b.)`                       | Normalizar para `ali-b`                                        |
| `1.` / `1)`                        | Normalizar para `item-1`                                       |
| `(NR)`                             | Remover do texto; é marca de nova redação                      |
| `(Revogado pela Lei ...)`          | Status `revogado`; não indexar como vigente                    |
| `Vide`, `Vide ADI`                 | Guardar como relação, não como dispositivo                     |
| Texto riscado                      | `texto_anterior`; fora do índice                               |
| Tabelas e anexos                   | Tratar em tabela separada (`annexes`); não é dispositivo legal |
| Numeração duplicada                | Resolver por caminho estrutural + versão                       |
| Dispositivo sem texto              | Não indexar; gerar alerta de ingestão                          |
| Alteração de numeração             | Nova versão; manter ID antigo como alias                       |

## 12. Validação

Antes de carregar no banco:

- [ ] Todo dispositivo-folha tem `parent_id`.
- [ ] Todo `artigo_id` existe como dispositivo.
- [ ] Nenhum `texto_literal` vazio.
- [ ] Nenhum texto riscado no `texto_literal`.
- [ ] Toda citação resolve para uma norma.
- [ ] Não há duas versões vigentes sobrepostas para o mesmo dispositivo.
- [ ] Nenhum dispositivo excede `max_length` sem split/falha explícita.
- [ ] O número de artigos parseados confere com o índice da norma.
- [ ] O hash é estável entre execuções.
- [ ] Amostra de 20 dispositivos foi conferida manualmente.
