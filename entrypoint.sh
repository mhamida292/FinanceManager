#!/usr/bin/env bash
set -euo pipefail

ROLE="${ROLE:-web}"

echo "[entrypoint] role=${ROLE}"

if [ "${ROLE}" = "web" ]; then
  echo "[entrypoint] running migrations"
  python manage.py migrate --noinput
  echo "[entrypoint] collecting static"
  python manage.py collectstatic --noinput
fi

exec "$@"
