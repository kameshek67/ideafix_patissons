FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    DB_PATH=/app/data/bvi_database.db \
    XLSX_PATH=/app/data/Olimpiady_BVI_100ballov.xlsx \
    FRONTEND_DIR=/app/frontend

WORKDIR /app/backend

COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/ /app/backend/
COPY frontend/ /app/frontend/
COPY data/ /app/data/

EXPOSE 8000

HEALTHCHECK --interval=15s --timeout=5s --start-period=90s --retries=5 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=4).status==200 else 1)"

# База строится при первом старте, если её ещё нет в /app/data.
CMD ["sh", "-c", "if [ ! -f \"$DB_PATH\" ]; then python ingest_data.py --xlsx \"$XLSX_PATH\" --db \"$DB_PATH\"; fi; exec uvicorn main:app --host 0.0.0.0 --port 8000"]
