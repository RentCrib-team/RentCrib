#!/usr/bin/env bash
# Free-tier single-service launcher: daphne + celery worker + celery beat all
# in one Render web service (free accounts get one service slot only).
#
# Restart behaviour: if ANY of the three processes exits, the whole container
# exits and Render restarts it. This keeps worker/beat crashes from silently
# hiding behind a healthy web process.
set +e

PORT="${PORT:-8000}"
cleanup() {
  kill 0 2>/dev/null
  wait 2>/dev/null
}
trap cleanup EXIT INT TERM

mkdir -p "${RENDER_DISK_PATH:-/var/data}/media"

# Redis Cloud free instances expose a single DB and reject `SELECT <n>`
# ("DB index is out of range"). The celery CLI reads CELERY_BROKER_URL and
# CELERY_RESULT_BACKEND from the environment with priority over django
# settings, so scrub the trailing /<n> here as well.
_celery_redis_normalize() {
  python3 -c '
import os, sys
u = os.getenv(sys.argv[1], "")
if u and "://" in u:
    scheme, _, rest = u.partition("://")
    host, _, db = rest.rpartition("/")
    if db.isdigit():
        u = f"{scheme}://{host}"
print(u)
' "$1"
}
export CELERY_BROKER_URL="$(_celery_redis_normalize CELERY_BROKER_URL)"
export CELERY_RESULT_BACKEND="$(_celery_redis_normalize CELERY_RESULT_BACKEND)"

echo "[start.sh] starting celery beat"
celery -A celery_app beat -l info &

echo "[start.sh] starting celery worker"
celery -A celery_app worker -l info --concurrency=1 -Q celery,emails,maintenance &

echo "[start.sh] starting daphne on :$PORT"
daphne -b 0.0.0.0 -p "$PORT" property.asgi:application &

# Block until the first process exits, then tear everything down.
wait -n
code=$?
echo "[start.sh] a process exited with code $code; shutting down"
exit "$code"