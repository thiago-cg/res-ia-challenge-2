-- Some sources (e.g. a collection of Súmulas) have no single number/year.
-- Keep the identity columns nullable instead of writing sentinel values.
ALTER TABLE norms ALTER COLUMN numero DROP NOT NULL;
ALTER TABLE norms ALTER COLUMN ano DROP NOT NULL;
