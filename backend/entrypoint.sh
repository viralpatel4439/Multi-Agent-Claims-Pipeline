#!/bin/sh
set -e

# Only the backend container runs migrations + seed.
# celery_worker sets RUN_MIGRATIONS=false so it starts immediately.
if [ "${RUN_MIGRATIONS:-true}" = "true" ]; then
  echo "→ Running database migrations..."
  alembic upgrade head

  echo "→ Seeding database..."
  python -m app.db.seed
fi

echo "→ Starting: $*"
exec "$@"
