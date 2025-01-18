FROM python:3.9-slim

WORKDIR /app

# Обновляем пакеты и устанавливаем зависимости для Pillow
RUN apt-get update && apt-get install -y \
    libjpeg62-turbo-dev \
    zlib1g-dev \
    && pip install --upgrade pip

COPY requirements.txt /app/

# Устанавливаем все зависимости из requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY . /app/

# Устанавливаем переменную окружения для Python
ENV PYTHONUNBUFFERED 1

# Запускаем миграции и Gunicorn
CMD ["bash", "-c", "python manage.py migrate && gunicorn --bind 0.0.0.0:8000 config.wsgi:application"]