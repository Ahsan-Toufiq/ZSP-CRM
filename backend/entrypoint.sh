#!/usr/bin/env sh
set -eu

if [ "$#" -gt 0 ]; then
    if [ "$#" -eq 1 ]; then
        exec /bin/sh -c "$1"
    fi
    exec "$@"
fi

python manage.py migrate --noinput
python manage.py collectstatic --noinput

exec gunicorn config.wsgi:application --bind "0.0.0.0:${PORT:-8000}" --workers "${WEB_CONCURRENCY:-3}"
