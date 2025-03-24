#!/bin/bash

# Ожидаем доступности PostgreSQL
echo "⏳ Waiting for PostgreSQL to be available..."
while ! nc -z db 5432; do
  sleep 1
done

# Миграции и collectstatic только для web (gunicorn)
if [ "$1" = "gunicorn" ]; then
  echo "✅ Running migrations..."
  python manage.py migrate --noinput

  echo "📦 Collecting static files..."
  python manage.py collectstatic --noinput
fi

echo "🚀 Starting: $@"
exec "$@"