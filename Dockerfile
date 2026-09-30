# Recruit — web push shortlist notifier
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Non-root runtime user
RUN useradd --create-home --shell /usr/sbin/nologin recruit

WORKDIR /srv

# deps first (layer caching)
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# app source + assets + scripts
COPY app ./app
COPY static ./static
COPY scripts ./scripts
COPY worker.py ./

# writable runtime dirs (db stays on a mounted volume)
RUN mkdir -p /data/db /data/logs /data/backups \
    && chown -R recruit:recruit /srv /data

USER recruit

ENV DATABASE_URL=sqlite:////data/db/recruit.db \
    LOG_DIR=/data/logs \
    DB_BACKUP_DIR=/data/backups

EXPOSE 8090

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD python -c "import urllib.request as u;u.urlopen('http://127.0.0.1:8090/health',timeout=3)"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8090", "--workers", "1"]