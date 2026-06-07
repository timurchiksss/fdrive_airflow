#!/usr/bin/env bash
set -euo pipefail

mkdir -p dumps

export PGHOST="${PGHOST:-localhost}"
export PGPORT="${PGPORT:-5432}"
export PGUSER="${PGUSER:-${USER:-postgres}}"
export PGDATABASE="${PGDATABASE:-fdrive_raw}"

stamp="$(date +%Y%m%d_%H%M%S)"
out="dumps/raw_${stamp}.dump"

pg_dump \
  --host "$PGHOST" \
  --port "$PGPORT" \
  --username "$PGUSER" \
  --dbname "$PGDATABASE" \
  --format custom \
  --no-owner \
  --no-acl \
  --schema raw \
  --file "$out"

echo "$out"
