#!/bin/sh
# Restore only to a NEW, explicitly named recovery database; never overwrite a live DB.
# Usage: sh deploy/restore.sh <db-container> <tfp_restore_name> <file.dump>
set -eu
if [ "$#" -ne 3 ]; then echo "Usage: $0 <db-container> <tfp_restore_name> <file.dump>" >&2; exit 2; fi
case "$2" in tfp_restore_?*) ;; *) echo "Database must begin with tfp_restore_ and have a suffix." >&2; exit 2 ;; esac
case "$2" in *[!a-z0-9_]*) echo "Only lowercase letters, digits and underscores are allowed." >&2; exit 2 ;; esac
if [ "${#2}" -gt 63 ] || [ ! -s "$3" ]; then echo "Invalid database name or missing/empty dump." >&2; exit 2; fi
# Validate archive before creating anything. createdb refuses an existing database.
docker exec -i "$1" pg_restore --list < "$3" > /dev/null
docker exec "$1" sh -c 'exec createdb -U "$POSTGRES_USER" -- "$1"' sh "$2"
if ! docker exec -i "$1" sh -c 'exec pg_restore -U "$POSTGRES_USER" -d "$1" --exit-on-error --no-owner --single-transaction' sh "$2" < "$3"; then
    echo "Restore failed. Recovery database retained for inspection; live database was not replaced." >&2
    exit 1
fi
echo "Restore completed in new database: $2 (not activated)"
