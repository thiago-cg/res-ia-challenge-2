-- Índice por tipo para o mapa de delegacias (issue #22: "índices por município e tipo").
-- O índice por município (uf, municipio) já vem da 006. Este cobre o filtro por tipo
-- (deam, nucleo_atendimento_mulher, delegacia_comum) dentro de uma UF.
-- Idempotente (IF NOT EXISTS): pode rodar de novo em um banco que já o tem.

CREATE INDEX IF NOT EXISTS services_tipo_idx ON services (uf, tipo);
