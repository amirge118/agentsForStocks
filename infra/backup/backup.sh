#!/bin/sh
# Daily pg_dump of the app database into /backups (profile "backup"), keeping
# BACKUP_KEEP_DAYS days; BACKUP_ONCE=1 writes one dump and exits. Restore one with:
#   gunzip -c backups/agentsforstocks-<stamp>.sql.gz | \
#     docker compose exec -T db psql -U "$POSTGRES_USER" -d "$POSTGRES_DB"
set -eu

: "${BACKUP_KEEP_DAYS:=14}"
: "${BACKUP_INTERVAL_SECONDS:=86400}"
export PGPASSWORD="$POSTGRES_PASSWORD"

while true; do
	stamp=$(date -u +%Y-%m-%dT%H%MZ)
	file="/backups/${POSTGRES_DB}-${stamp}.sql.gz"
	if pg_dump -h db -U "$POSTGRES_USER" -d "$POSTGRES_DB" --no-owner | gzip > "$file.part"; then
		mv "$file.part" "$file"
		echo "backup written: $file ($(du -h "$file" | cut -f1))"
	else
		rm -f "$file.part"
		echo "backup FAILED at $stamp" >&2
	fi
	find /backups -name "${POSTGRES_DB}-*.sql.gz" -mtime +"$BACKUP_KEEP_DAYS" -print -delete
	[ "${BACKUP_ONCE:-}" = 1 ] && exit 0
	sleep "$BACKUP_INTERVAL_SECONDS"
done
