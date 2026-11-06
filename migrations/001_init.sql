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

CREATE TABLE services (
    id           bigserial PRIMARY KEY,
    uf           char(2) NOT NULL,
    municipio    text NOT NULL,
    nome         text NOT NULL,
    tipo         text NOT NULL,
    endereco     text,
    telefone     text,
    horario      text,
    fonte_url    text NOT NULL,
    atualizado_em date NOT NULL
);

CREATE FUNCTION device_versions_check_overlap() RETURNS trigger AS $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM device_versions dv
        WHERE dv.device_id = NEW.device_id
          AND dv.id IS DISTINCT FROM NEW.id
          AND daterange(dv.vigencia_inicio, dv.vigencia_fim, '[]')
              && daterange(NEW.vigencia_inicio, NEW.vigencia_fim, '[]')
    ) THEN
        RAISE EXCEPTION 'overlapping vigencia for device %', NEW.device_id;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER device_versions_no_overlap
    BEFORE INSERT OR UPDATE ON device_versions
    FOR EACH ROW EXECUTE FUNCTION device_versions_check_overlap();
