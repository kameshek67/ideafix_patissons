set shell := ["bash", "-euo", "pipefail", "-c"]
set dotenv-load

# команды бэкенда запускаются из корня репозитория (пути вроде data/… в аргументах — от него)
uv := "uv run --project backend"

default:
    @just --list

# поднять окружение для разработки (PostgreSQL, Redis, RabbitMQ)
up:
    docker compose -f docker-compose.yml -f infra/compose.dev.yaml up -d --wait postgres redis rabbitmq

down:
    docker compose -f docker-compose.yml -f infra/compose.dev.yaml down

# применить миграции
migrate:
    cd backend/db && uv run alembic upgrade head

# собрать базу из data/Olimpiady_BVI_100ballov.xlsx (одной транзакцией)
seed: migrate
    {{uv}} olymp-ingest

# проверка качества собранной базы (--check-links — плюс ссылки по сети)
validate *ARGS:
    {{uv}} olymp-validate {{ARGS}}

# обновить снимок выдачи data/snapshot/benefits.tsv из текущей базы (после осознанной правки разбора)
snapshot:
    {{uv}} olymp-snapshot

# что поменялось в выдаче относительно снимка (код выхода 1, если расходится)
data-diff:
    {{uv}} olymp-snapshot --check

# открытый датасет льгот: data/release/olymp-benefits.jsonl.gz и meta.json рядом
dataset *ARGS:
    {{uv}} olymp-export-dataset {{ARGS}}

# обойти страницы приёмных комиссий и обновить ссылки на документы
refresh-sources *ARGS:
    {{uv}} olymp-refresh-sources {{ARGS}}

# собрать официальные материалы олимпиад (положения, задания, расписания) с их сайтов
materials:
    {{uv}} olymp-materials

# ИИ-сверка строк льгот с документами вузов: --sample 20, --university итмо, --dry-run
ai-verify *ARGS:
    {{uv}} olymp-ai-verify {{ARGS}}

# льготы из документа вуза в JSON кодом: just extract --url URL --university ВУЗ | --from-gold
extract *ARGS:
    {{uv}} olymp-extract {{ARGS}}

# оценка извлечения льгот по эталону: just eval-extract --pred data/extracted | --pred db [--check-quotes --json out.json]
eval-extract *ARGS:
    {{uv}} olymp-eval-extract {{ARGS}}

# исправленные жалобы «не совпадает с документом» → data/regressions/reports.json (export) или проверка по базе (check)
report-regressions *ARGS:
    {{uv}} olymp-report-regressions {{ARGS}}

# скачать документы вузов в кэш и пересобрать справочный поиск (passages): just rag-fetch [--workers 6]
rag-fetch *ARGS:
    {{uv}} olymp-passages --fetch {{ARGS}}

# пересчитать анализ данных: data/analysis/results.json и графики docs/img (нужна собранная база)
analysis *ARGS:
    uv run --project backend --with matplotlib olymp-analysis --charts {{ARGS}}

# воркер фоновых задач (Dramatiq + RabbitMQ)
worker:
    {{uv}} dramatiq olymp_workers.tasks --processes 1 --threads 2

api:
    {{uv}} uvicorn olymp_api.main:app --reload --port 8000

web:
    cd frontend && npm run dev

# мини-приложение MAX: проверить токен бота (OLYMP_MAX_BOT_TOKEN в .env) и получить ссылки
max-check:
    {{uv}} olymp-max-bot check

# ссылка, открывающая сайт «как из MAX» в обычном браузере (--start diplomas — сразу дипломы)
max-link *ARGS:
    {{uv}} olymp-max-link {{ARGS}}

# оценить модель на наборе вопросов: --provider имя (профиль из OLYMP_LLM_PROFILES) или stub без
# LLM-API, --model, --limit 5 --pause 10, --out отчёт.json (тратит лимит провайдера)
assistant-eval *ARGS:
    {{uv}} python -m olymp_api.modules.assistant.evaluate {{ARGS}}

# пересобрать ожидания набора из собранной базы: backend/api/tests/assistant_questions.jsonl -> assistant_cases.jsonl
assistant-cases:
    {{uv}} python -m olymp_api.modules.assistant.build_cases

# пересчитать проверки и метрики сохранённого прогона без вызова модели:
# just assistant-rescore отчёт.json --out новый.json [--summary data/eval/assistant/summary.json]
assistant-rescore *ARGS:
    {{uv}} python -m olymp_api.modules.assistant.rescore {{ARGS}}

# ИИ-черновики карточек олимпиад: just ai-cards sites | just ai-cards draft --top 50 (нужны база и OLYMP_LLM_*)
ai-cards *ARGS:
    {{uv}} olymp-ai-cards {{ARGS}}

# сообщения «Нашли ошибку в данных» в CSV: just reports --all > reports.csv
reports *ARGS:
    {{uv}} olymp-export-reports {{ARGS}}

# перечень олимпиад РСОШ на 2026/27 с rsr-olymp.ru -> data/rsosh_2026_27.json (раз в сезон): just rsosh --dry-run
rsosh *ARGS:
    {{uv}} olymp-rsosh {{ARGS}}

# пересоздать контракт API и клиент для сайта после изменения эндпоинтов
openapi:
    {{uv}} python -m olymp_api.openapi_cli > docs/openapi.json
    cd frontend && npm run gen:api

lint:
    cd backend && uv run ruff check .
    cd backend && uv run ruff format --check .
    cd backend && uv run mypy api workers domain db llm mcp
    cd backend && uv run lint-imports
    cd frontend && npm run lint

test:
    cd backend && uv run pytest -q
    cd frontend && npm test

# весь стек в контейнерах: сайт :8080, API :8000
app:
    docker compose up --build -d

# новая миграция Alembic по изменениям моделей: just migration "описание" (проверь файл руками!)
migration MESSAGE:
    cd backend/db && uv run alembic revision --autogenerate -m "{{MESSAGE}}"

# всё, что проверяет CI (для тестов с базой нужен `just up`)
check: lint test
