FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    FLASK_DEBUG=0

WORKDIR /app

COPY apps/api/requirements.txt /app/apps/api/requirements.txt
RUN pip install --no-cache-dir -r /app/apps/api/requirements.txt

COPY apps /app/apps
COPY ml /app/ml
COPY run.py /app/run.py

# Non-root runtime user
RUN useradd --create-home agriq && chown -R agriq:agriq /app
USER agriq

WORKDIR /app/apps/api

EXPOSE 8000

# Production WSGI target (wsgi.py); requires AGRIQ_ENV=production plus
# PostgreSQL DATABASE_URL and Redis RATELIMIT_STORAGE_URI to boot.
CMD ["gunicorn", "--bind", "0.0.0.0:8000", "--workers", "2", "--threads", "4", "wsgi:app"]
