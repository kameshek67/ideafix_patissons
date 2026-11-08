# Разработка: окружение и запуск

## Что поставить

| Инструмент | Зачем | Windows | macOS / Linux |
|---|---|---|---|
| uv ≥ 0.13 | Python 3.13 и зависимости | `winget install astral-sh.uv` | `curl -LsSf https://astral.sh/uv/install.sh \| sh` |
| Node.js ≥ 22 | сайт | `winget install OpenJS.NodeJS.LTS` | nvm / пакетный менеджер |
| Docker | PostgreSQL, Redis, RabbitMQ, весь стек | Docker Desktop (WSL 2) | Docker Engine / Desktop |
| just | короткие команды | `winget install Casey.Just` | `brew install just` / пакет |
| gh | PR, задачи (`just tasks` видит открытые PR) | `winget install GitHub.cli` | `brew install gh` |

На Windows `just` запускает рецепты через bash: нужен Git Bash (ставится с Git for Windows).
После установки перезапусти терминал, чтобы обновился PATH.

## Первый запуск

```bash
git clone git@github.com:Raytist/ideafix_patissons.git && cd ideafix_patissons
git switch dev
cp .env.example .env
uv sync --all-packages && npm install
just up          # PostgreSQL :5432, Redis :6379, RabbitMQ :5672 (infra/compose.yaml)
just seed        # миграции + сборка базы из XLSX (~1 мин)
just api         # http://localhost:8000/docs
just web         # http://localhost:3000 (второй терминал)
```

Без just на Windows: `.\run_local.ps1` (`-Rebuild` — пересобрать базу, `-ApiPort 8010` —
если порт занят); на Linux/macOS — `./run_local.sh`.

Весь стек в контейнерах (как на демо): `docker compose up --build -d` → сайт :8080, API :8000.

## Ежедневные команды

```bash
just check              # всё, что проверит CI (lint + test + tasks-check)
just lint               # ruff, format, mypy, import-linter, tsc
just test               # pytest + vitest
just openapi            # после изменения эндпоинтов
just migration "текст"  # новая миграция Alembic (autogenerate) — проверь файл руками
just tasks / tasks-next # доска задач / что взять
just max-link --start diplomas   # открыть сайт «как из MAX» (нужен OLYMP_MAX_BOT_TOKEN, любой для локальной проверки)
```

## Переменные окружения

Все — с префиксом `OLYMP_`, читаются из `.env` (шаблон `.env.example`, секретов в нём нет).

| Переменная | По умолчанию | Что |
|---|---|---|
| `OLYMP_DATABASE_URL` | `postgresql+psycopg://olymp:olymp@localhost:5432/olymp` | БД (API сам переходит на asyncpg) |
| `OLYMP_REDIS_URL` | — | кэш и лимиты; без него — в памяти |
| `OLYMP_RABBITMQ_URL` | — | очередь Dramatiq |
| `OLYMP_API_URL` | `http://127.0.0.1:8000` | куда сайт проксирует `/api/v1/*` |
| `OLYMP_RATE_LIMIT_REQUESTS` / `_WINDOW` | 600 / 60 | лимит запросов на IP; 0 — выключен |
| `OLYMP_CACHE_TTL` | 600 | кэш ответов поиска, секунд |
| `OLYMP_MAX_BOT_TOKEN`, `OLYMP_MAX_BOT_NAME` | — | мини-приложение MAX (секрет!) |
| `OLYMP_MAX_INIT_DATA_TTL` | 86400 | срок годности данных запуска MAX |
| `OLYMP_LLM_BASE_URL`, `OLYMP_LLM_API_KEY`, `OLYMP_LLM_MODEL` | — | ИИ-помощник: без любого из них он выключен (ключ — секрет!). Подходит любой OpenAI-совместимый провайдер; OpenRouter: `https://openrouter.ai/api/v1`, на стенде — `https://ai.starimg.ru/v1` и `deepseek-v4.1-flash` |
| `OLYMP_LLM_FALLBACK_MODEL` | — | резервная модель |
| `OLYMP_LLM_ENABLED` | `true` | мгновенно выключить помощника |
| `OLYMP_LLM_DAILY_REQUESTS` | 45 | обращений к модели в сутки на весь сервис; 0 — без ограничения |
| `OLYMP_LLM_DENY_DATA_COLLECTION` | `true` | OpenRouter: не отправлять запросы провайдерам, которые хранят данные |
| `OLYMP_TEST_DATABASE_URL` | как `DATABASE_URL` | сервер для временных баз тестов |
| `OLYMP_WEB_PORT`, `OLYMP_API_PORT` | 8080, 8000 | порты Docker-стека |

## Частые проблемы

| Симптом | Причина и решение |
|---|---|
| Тесты «skipped» | PostgreSQL не запущен: `just up`. Пропуск не равен прохождению |
| `port is already allocated` | Порт занят (часто старым прототипом `bvi-*`): `docker stop bvi-frontend bvi-backend` или `OLYMP_WEB_PORT=18080 OLYMP_API_PORT=18000` |
| `UnicodeEncodeError` на Windows | `PYTHONUTF8=1` (уже в `.env.example`; для Git Bash — `export PYTHONUTF8=1`) |
| Сборка Docker: `connecting to 127.0.0.1:…: actively refused` | Docker ходит в интернет через VPN-прокси: включи VPN на время сборки |
| CI: «контракт API неактуален» | Запусти `just openapi` и закоммить оба файла |
| `/readyz` → 503 | База не собрана: `just seed` |
| В MAX «Сохранено на этом устройстве» | API не видит токен бота: проверь `.env` и `/api/v1/max/config` |
