#!/usr/bin/env bash
# ── Backup diario de PostgreSQL (educurator + langfuse) ─────────────────────
#
# Uso (cron en el servidor de producción):
#   0 3 * * * /ruta/Educurator/scripts/backup_db.sh >> /var/log/educurator-backup.log 2>&1
#
# Genera dumps comprimidos en ./backups/ y conserva los últimos 14 días.
# Restaurar:
#   gunzip -c backups/educurator-FECHA.sql.gz | \
#     docker compose -f docker-compose.prod.yml exec -T db psql -U postgres educurator

set -euo pipefail

# Directorio del repo (padre de scripts/), independiente de desde dónde se invoque
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
COMPOSE_FILE="${COMPOSE_FILE:-$REPO_DIR/docker-compose.prod.yml}"
BACKUP_DIR="${BACKUP_DIR:-$REPO_DIR/backups}"
RETENTION_DAYS="${RETENTION_DAYS:-14}"
STAMP="$(date +%Y%m%d-%H%M)"

mkdir -p "$BACKUP_DIR"

echo "[$(date -Iseconds)] Iniciando backup..."

for DB in educurator langfuse; do
  OUT="$BACKUP_DIR/${DB}-${STAMP}.sql.gz"
  if docker compose -f "$COMPOSE_FILE" exec -T db \
      pg_dump -U postgres --no-owner "$DB" | gzip > "$OUT"; then
    echo "  OK  $OUT ($(du -h "$OUT" | cut -f1))"
  else
    echo "  ERROR haciendo dump de $DB" >&2
    rm -f "$OUT"
    exit 1
  fi
done

# Rotación: eliminar backups más viejos que RETENTION_DAYS
find "$BACKUP_DIR" -name "*.sql.gz" -mtime +"$RETENTION_DAYS" -delete

echo "[$(date -Iseconds)] Backup completado. Retención: ${RETENTION_DAYS} días."
