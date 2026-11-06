#!/usr/bin/env sh
# OPS-02: restore a pg_dump custom-format archive into DATABASE_URL.
# Refuses to touch a production-looking database unless ALLOW_PROD_RESTORE=1.
set -eu

if [ -z "${DATABASE_URL:-}" ]; then
    echo "error: DATABASE_URL is not set" >&2
    exit 1
fi

if [ "$#" -lt 1 ]; then
    echo "usage: $0 <dump-file>" >&2
    exit 1
fi

dump_path="$1"
if [ ! -f "$dump_path" ]; then
    echo "error: dump file not found: ${dump_path}" >&2
    exit 1
fi

PG_RESTORE="${PG_RESTORE:-pg_restore}"

if ! command -v "$PG_RESTORE" >/dev/null 2>&1; then
    echo "error: ${PG_RESTORE} not found in PATH" >&2
    exit 1
fi

db_name="${DATABASE_URL##*/}"
db_name="${db_name%%\?*}"
db_name="$(printf '%s' "$db_name" | tr '[:upper:]' '[:lower:]')"

case "$db_name" in
    *test* | *restore*) ;;
    *)
        if [ "${ALLOW_PROD_RESTORE:-0}" != "1" ]; then
            echo "error: refusing to restore into '${db_name}': name does not contain 'test' or 'restore'." >&2
            echo "hint: set ALLOW_PROD_RESTORE=1 only for an intentional production restore." >&2
            exit 1
        fi
        ;;
esac

echo "restoring ${dump_path} into database '${db_name}'"
"$PG_RESTORE" \
    --dbname="$DATABASE_URL" \
    --clean \
    --if-exists \
    --no-owner \
    "$dump_path"

echo "restore complete: '${db_name}' <- ${dump_path}"
