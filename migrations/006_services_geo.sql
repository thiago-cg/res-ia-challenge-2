-- Geolocated services (delegacias) for the "nearest police station" map.
-- Idempotent (IF NOT EXISTS): safe to re-run on a database that already has it.

ALTER TABLE services
    ADD COLUMN IF NOT EXISTS latitude double precision,
    ADD COLUMN IF NOT EXISTS longitude double precision,
    -- false = approximate point that still has to be conferred on the map
    ADD COLUMN IF NOT EXISTS coordenada_verificada boolean NOT NULL DEFAULT false,
    -- where the row came from: 'curado' (official page, typed by hand) or 'osm'
    ADD COLUMN IF NOT EXISTS origem text NOT NULL DEFAULT 'curado';

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'services_tipo_check') THEN
        ALTER TABLE services ADD CONSTRAINT services_tipo_check
            CHECK (tipo IN ('deam', 'nucleo_atendimento_mulher', 'delegacia_comum'));
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'services_coords_check') THEN
        ALTER TABLE services ADD CONSTRAINT services_coords_check
            CHECK (
                (latitude IS NULL AND longitude IS NULL)
                OR (latitude BETWEEN -34 AND 6 AND longitude BETWEEN -75 AND -32)
            );
    END IF;
END $$;

CREATE UNIQUE INDEX IF NOT EXISTS services_identity_idx
    ON services (uf, municipio, nome, (coalesce(endereco, '')));
CREATE INDEX IF NOT EXISTS services_geo_idx ON services (latitude, longitude);
CREATE INDEX IF NOT EXISTS services_municipio_idx ON services (uf, municipio);
