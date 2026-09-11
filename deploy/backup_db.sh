#!/usr/bin/env bash
set -euo pipefail

APP_DIR=/var/www/echolog
BACKUP_DIR=/var/backups/echolog
mkdir -p "$BACKUP_DIR"

# systemd service loads .env before this script, so POSTGRES_* are available.
STAMP=$(date +%Y%m%d_%H%M%S)
OUT="$BACKUP_DIR/echolog_${STAMP}.sql.gz"

PGPASSWORD="${POSTGRES_PASSWORD}" pg_dump \
  -h "${POSTGRES_HOST:-127.0.0.1}" \
  -p "${POSTGRES_PORT:-5432}" \
  -U "${POSTGRES_USER}" \
  -d "${POSTGRES_DB}" \
  --no-owner --no-acl | gzip -9 > "$OUT"

# Keep 30 days by default.
find "$BACKUP_DIR" -type f -name 'echolog_*.sql.gz' -mtime +30 -delete
printf 'Created %s\n' "$OUT"
