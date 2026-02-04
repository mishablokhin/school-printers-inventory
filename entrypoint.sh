#!/usr/bin/env sh
set -e

echo "Running migrations..."
python manage.py migrate --noinput

echo "Collecting static..."
python manage.py collectstatic --noinput || true

echo "Starting gunicorn..."
gunicorn school_cartridges.wsgi:application       --bind 0.0.0.0:8000       --workers ${GUNICORN_WORKERS:-2}       --timeout ${GUNICORN_TIMEOUT:-60}
