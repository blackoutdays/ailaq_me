#!/bin/bash

set -e

echo "⏳ Waiting for PostgreSQL..."
while ! nc -z db 5432; do
  sleep 1
done

echo "⏳ Waiting for RabbitMQ..."
while ! nc -z rabbitmq 5672; do
  sleep 1
done

if [ "$1" = "gunicorn" ]; then
  echo "⚙️ Applying migrations..."
  python manage.py migrate --noinput
  echo "📦 Collecting static files..."
  python manage.py collectstatic --noinput
fi

exec "$@"