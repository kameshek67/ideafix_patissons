#!/usr/bin/env bash
# Локальный запуск для разработки (Linux/macOS), если нет just.
#   ./run_local.sh            — окружение в Docker, API (:8000) и сайт (:3000)
#   ./run_local.sh --rebuild  — пересобрать базу из XLSX
# Нужны Docker, uv и Node.js 22+.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"
API_PORT="${API_PORT:-8000}"

export OLYMP_DATABASE_URL="postgresql+psycopg://olymp:olymp@localhost:5432/olymp"
export OLYMP_REDIS_URL="redis://localhost:6379/0"
export OLYMP_RABBITMQ_URL="amqp://olymp:olymp@localhost:5672/"
export OLYMP_API_URL="http://127.0.0.1:$API_PORT"

docker compose -f infra/compose.yaml up -d --wait
uv sync --all-packages
[[ -d node_modules ]] || npm install --no-audit --no-fund
(cd packages/db && uv run alembic upgrade head)
if [[ "${1:-}" == "--rebuild" ]]; then uv run olymp-ingest; else uv run olymp-ingest --if-empty; fi

uv run uvicorn olymp_api.main:app --port "$API_PORT" &
API_PID=$!
trap 'kill $API_PID 2>/dev/null' EXIT

echo
echo "Сайт: http://localhost:3000    API и Swagger: http://localhost:$API_PORT/docs"
echo
npm run dev --workspace olymp-web
