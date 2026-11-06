set shell := ["bash", "-euo", "pipefail", "-c"]
set dotenv-load

default:
    @just --list

# поднять окружение для разработки (PostgreSQL, Redis, RabbitMQ)
up:
    docker compose -f infra/compose.yaml up -d --wait

down:
    docker compose -f infra/compose.yaml down

# применить миграции
migrate:
    cd packages/db && uv run alembic upgrade head

# собрать базу из data/Olimpiady_BVI_100ballov.xlsx (одной транзакцией)
seed: migrate
    uv run olymp-ingest

# проверка качества собранной базы (--check-links — плюс ссылки по сети)
validate *ARGS:
    uv run olymp-validate {{ARGS}}

# обойти страницы приёмных комиссий и обновить ссылки на документы
refresh-sources *ARGS:
    uv run olymp-refresh-sources {{ARGS}}

# воркер фоновых задач (Dramatiq + RabbitMQ)
worker:
    uv run dramatiq olymp_workers.tasks --processes 1 --threads 2

api:
    uv run uvicorn olymp_api.main:app --reload --port 8000

web:
    npm run dev --workspace olymp-web

# пересоздать контракт API и клиент для сайта после изменения эндпоинтов
openapi:
    uv run python -m olymp_api.openapi_cli > docs/openapi.json
    npm run gen:api --workspace olymp-web

lint:
    uv run ruff check .
    uv run ruff format --check .
    uv run mypy packages apps
    uv run lint-imports
    npm run lint --workspace olymp-web

test:
    uv run pytest -q
    npm test --workspace olymp-web

# сверить ответы API с прототипом из ветки main (он должен работать на :8000)
compare *ARGS:
    uv run python scripts/compare_with_prototype.py {{ARGS}}

# весь стек в контейнерах: сайт :8080, API :8000
app:
    docker compose up --build -d
