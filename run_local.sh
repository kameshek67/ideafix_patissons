#!/usr/bin/env bash
# Локальный запуск без Docker (Linux/macOS).
#   ./run_local.sh            — собрать базу (если её нет) и поднять сервер на :8000
#   ./run_local.sh --rebuild  — пересобрать базу с нуля
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DB="$ROOT/data/bvi_database.db"
PORT="${PORT:-8000}"

cd "$ROOT/backend"
python -m pip install -r requirements.txt --quiet

if [[ "${1:-}" == "--rebuild" ]]; then rm -f "$DB"; fi
if [[ ! -f "$DB" ]]; then python ingest_data.py; fi

echo
echo "Приложение: http://localhost:$PORT    Swagger: http://localhost:$PORT/docs"
echo
exec python -m uvicorn main:app --host 0.0.0.0 --port "$PORT"
