#!/usr/bin/env sh
# OPS-02: local Postgres backup in pg_dump custom format.
# Reads DATABASE_URL from the environment; never hardcode credentials here.
set -eu

if [ -z "${DATABASE_URL:-}" ]; then
    echo "error: DATABASE_URL is not set" >&2
    exit 1
fi

PG_DUMP="${PG_DUMP:-pg_dump}"

if ! command -v "$PG_DUMP" >/dev/null 2>&1; then
    echo "error: ${PG_DUMP} not found in PATH" >&2
    exit 1
fi

BACKUP_DIR="${BACKUP_DIR:-./backups}"
mkdir -p "$BACKUP_DIR"

dump_path="${BACKUP_DIR}/violencia-$(date -u +%Y%m%dT%H%M%SZ).dump"

"$PG_DUMP" \
    --dbname="$DATABASE_URL" \
    --format=custom \
    --no-owner \
    --no-privileges \
    --file="$dump_path"

if command -v sha256sum >/dev/null 2>&1; then
    sha256sum "$dump_path" >"${dump_path}.sha256"
elif command -v shasum >/dev/null 2>&1; then
    shasum -a 256 "$dump_path" >"${dump_path}.sha256"
else
    echo "error: neither sha256sum nor shasum found in PATH" >&2
    exit 1
fi

echo "backup written: ${dump_path}"
echo "checksum written: ${dump_path}.sha256"
