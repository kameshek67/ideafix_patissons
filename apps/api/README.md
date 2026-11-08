# apps/api — REST API

FastAPI-сервис «Олимпа»: каталог вузов и олимпиад, двусторонний поиск льгот, подбор по дипломам,
профиль пользователя MAX. Модульный монолит ([ADR 0001](../../docs/adr/0001-modular-monolith.md)).

## Запуск

```bash
just up && just seed     # PostgreSQL (+ Redis) и собранная база
just api                 # http://localhost:8000, Swagger — /docs
```

Без just: `uv run uvicorn olymp_api.main:app --reload --port 8000`. В Docker — сервис `api`.

## Устройство

```
src/olymp_api/
  main.py            create_app(): middleware (лимит запросов, request-id, заголовки), /healthz, /readyz, роутеры
  settings.py        настройки OLYMP_* из окружения и .env
  db.py              async-движок, get_session, data_version() — время сборки базы для ключей кэша
  errors.py          ошибки RFC 9457 (problem+json)
  redis_support.py   кэш и окно лимита; без Redis — в памяти процесса
  max_auth.py        проверка подписи initData MAX → MaxUser
  metrics.py         Prometheus /metrics
  olympiads.py, universities.py, schemas.py   общие запросы и схемы для модулей
  openapi_cli.py     печатает контракт → docs/openapi.json (just openapi)
  modules/
    catalog/         /v1/stats, /regions, /universities, /programs, /olympiads, /olympiads/{id}/profiles
    search/          /v1/search/by-program, /v1/search/by-olympiad
    achievements/    «Мои дипломы»: /v1/achievements/*, /v1/max/config, /v1/me/diplomas
    sharing/         «Поделиться»: /v1/shares (снимки экранов по стабильным ключам)
    assistant/       ИИ-помощник: /v1/assistant/*, инструменты поиска, оценка модели
tests/               тесты на собранной базе (httpx + ASGI)
```

Модуль = `router.py` (HTTP, параметры, кэш) + `schemas.py` (Pydantic) + `service.py` (SQL и логика).
Модули не импортируют друг друга — проверяет `lint-imports`.

Все эндпоинты и соглашения — [docs/architecture/api.md](../../docs/architecture/api.md).

## Настройки

| Переменная | По умолчанию | Что |
|---|---|---|
| `OLYMP_DATABASE_URL` | — | PostgreSQL (`postgresql+asyncpg://…` или `+psycopg`, переключится сам) |
| `OLYMP_REDIS_URL` | — | кэш и лимиты; без него — в памяти |
| `OLYMP_RATE_LIMIT_REQUESTS` / `_WINDOW` | 600 / 60 | лимит запросов на IP |
| `OLYMP_CACHE_TTL` | 600 | кэш ответов поиска, секунд |
| `OLYMP_MAX_BOT_TOKEN`, `OLYMP_MAX_BOT_NAME` | — | вход через MAX; без токена дипломы хранятся на устройстве |
| `OLYMP_MAX_INIT_DATA_TTL` | 86400 | срок годности данных запуска MAX |

## Тесты

```bash
just up                       # нужен PostgreSQL
uv run pytest apps/api -q
```

База собирается из настоящего XLSX один раз на прогон (корневой `conftest.py`). Без PostgreSQL
тесты пропускаются.

## Правила разработки

Общие правила — [CONTRIBUTING.md](../../CONTRIBUTING.md).

**Новый эндпоинт.**
1. Схема ответа — в `schemas.py`, SQL и логика — в `service.py`, маршрут — в `router.py`
   с `response_model` и docstring (он попадает в Swagger). Роутер тонкий.
2. Публичные маршруты — под `/v1` (префикс ставит `main.py`). Ошибки — `HTTPException` или
   `errors.problem(...)`.
3. Ответы поиска кэшируй через `cache_get/cache_set`, ключ включает `data_version()`.
4. Тест в `apps/api/tests/` на собранной базе (фикстура `client`).
5. `just openapi` → закоммить `docs/openapi.json` и `packages/api-client/schema.d.ts`.

**Новый модуль.** `modules/<имя>/{router,schemas,service}.py`, подключение в `main.py`, строка в
контракте независимости в корневом `pyproject.toml`. Модули не импортируют друг друга: общее — в
`olymp_api/*.py` или `packages/domain`.

**Пользователь MAX.** Эндпоинты с данными пользователя — заголовок `X-Max-Init-Data` и
`Depends(max_user)`. Без `OLYMP_MAX_BOT_TOKEN` они отвечают 503. id и имя пользователя MAX не
логируем и никуда не передаём (в том числе в LLM).
