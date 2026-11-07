# Стек

| Слой | Технология | Версия | Зачем | Где настроено |
|---|---|---|---|---|
| Язык бэкенда | Python | 3.13 | Разбор XLSX/PDF, обработка текста, один язык для API и данных | `pyproject.toml` |
| Пакеты Python | uv (workspace) | 0.13 | Быстрая установка, lock-файл, монорепозиторий из 4 пакетов | `pyproject.toml`, `uv.lock` |
| API | FastAPI + Pydantic 2 | — | Типизированные эндпоинты, OpenAPI из кода | `apps/api` |
| ORM / миграции | SQLAlchemy 2 + Alembic | — | Модели в одном пакете, схема только миграциями | `packages/db` |
| БД | PostgreSQL (образ pgvector/pg17) | 17 | Полнотекстовый поиск, транзакционная пересборка; pgvector — задел под ИИ-поиск | `infra/compose.yaml` |
| Драйверы | asyncpg (API), psycopg 3 (сборка, миграции) | — | Асинхронный API, синхронная пакетная запись | `OLYMP_DATABASE_URL` |
| Кэш, лимиты | Redis | 7 | Кэш ответов поиска, окно лимита запросов; необязателен | `redis_support.py` |
| Фоновые задачи | Dramatiq + RabbitMQ | 4 | Обход сайтов вузов, пересборка по команде | `apps/workers/tasks.py` |
| Логи / метрики | structlog (JSON), prometheus-client | — | `request_id` в каждом логе, `/metrics` | `main.py`, `metrics.py` |
| Фронтенд | Next.js (App Router) + React | 16 / 19 | Прокси к API на том же origin, сборка, SSR-готовность | `apps/web` |
| Данные на клиенте | TanStack Query 5 | — | Кэш запросов, повторы, состояния загрузки | `providers.tsx` |
| Клиент API | openapi-typescript + openapi-fetch | — | Типы из контракта, без ручных интерфейсов | `packages/api-client` |
| Стили | Tailwind CSS (зафиксирован) + `styles.css` | 3.4.16 | Пиксельное совпадение с прототипом | `tailwind.config.ts` |
| Шрифт | Onest (`@fontsource-variable`) | — | Раздаётся с сайта, без Google Fonts — важно для MAX | `layout.tsx` |
| Мини-приложение | MAX Bridge | — | Вход, кнопка «Назад», ссылки, «Поделиться» | `lib/max.ts` |
| Тесты Python | pytest, pytest-asyncio, httpx | — | Unit + интеграционные на настоящей сборке базы | корневой `conftest.py` |
| Тесты web | Vitest + Testing Library + jsdom | — | Чистые функции и компоненты | `vitest.config.mts` |
| Качество | ruff, mypy strict, import-linter, tsc, gitleaks | — | Стиль, типы, границы модулей, секреты | CI |
| Запуск | Docker Compose, just | — | Одна команда на всё; профили tunnel/https/bot | `docker-compose.yml`, `justfile` |
| HTTPS | Cloudflare quick tunnel / Caddy | — | MAX открывает мини-приложения только по https | профили compose |
| CI | GitHub Actions | — | Линтеры, тесты с PostgreSQL, актуальность контракта, секреты | `.github/workflows/ci.yml` |

## Правила выбора зависимостей

- Новая зависимость — только если без неё нужно написать больше ~50 строк нетривиального кода.
  Укажи в PR, зачем она и чем лучше альтернатив.
- Python: `uv add --package <olymp-api|olymp-workers|olymp-domain|olymp-db> <пакет>`;
  dev-инструменты — `uv add --dev`. JS: `npm install <пакет> --workspace olymp-web`.
- `olymp-domain` не получает зависимостей от сети и БД.
- UI-библиотеки компонентов не добавляем: интерфейс собран на классах прототипа.
- Tailwind не обновляем (3.4.16), иначе разъедется вёрстка относительно макета.
