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