#!/bin/bash

# Ожидаем доступности PostgreSQL
echo "⏳ Waiting for PostgreSQL to be available..."
while ! nc -z db 5432; do
  sleep 1
done

# Применяем миграции
echo "✅ Running migrations..."
python manage.py migrate --noinput

# Собираем статику (для веб-приложения)
if [ "$1" = "gunicorn" ]; then
  echo "📦 Collecting static files..."
  python manage.py collectstatic --noinput
fi

# Выполняем переданную команду (например, gunicorn или celery)
echo "🚀 Starting: $@"
exec "$@"