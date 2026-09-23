#!/bin/sh
# Run as PUID:PGID (linuxserver/DockSTARTer convention) so edited episodes keep
# the ownership Audiobookshelf expects. Only DATA_DIR is chowned; the podcast
# library is never chowned.
set -e
PUID="${PUID:-1000}"
PGID="${PGID:-1000}"
umask "${UMASK:-002}"
mkdir -p "$DATA_DIR"
if [ "$(id -u)" = "0" ]; then
  chown -R "$PUID:$PGID" "$DATA_DIR"
  exec su-exec "$PUID:$PGID" "$@"
fi
exec "$@"
