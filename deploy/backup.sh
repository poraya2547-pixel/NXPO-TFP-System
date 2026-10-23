#!/bin/sh
# Usage: sh deploy/backup.sh <db-container> <new-file.dump>
# Private custom-format dump. Existing files are never overwritten.
set -eu
if [ "$#" -ne 2 ]; then echo "Usage: $0 <db-container> <new-file.dump>" >&2; exit 2; fi
umask 077
set -C
if ! docker exec "$1" sh -c 'exec pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" --format=custom --no-owner' > "$2"; then
    echo "Backup failed. Do not use the output as a valid backup; inspect it before retrying with a new filename." >&2
    exit 1
fi
echo "Backup completed: $2"
