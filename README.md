# Олимп — куда поступить по олимпиаде

Сервис и мини-приложение мессенджера **MAX**, которое отвечает школьнику, где его олимпиадный
диплом даёт **БВИ** (поступление без экзаменов) или **100 баллов** за ЕГЭ. Учитываются условия
вуза: степень диплома, класс, год, профиль. У каждой льготы есть ссылка на документ приёмной комиссии.

- **Вуз → олимпиады.** Выбрал вуз и направление — видишь, какие олимпиады дают льготы и что нужно подтвердить ЕГЭ.
- **Олимпиада → вузы.** Ввёл «вышка», «всош» или «пвг» — видишь все вузы, где она даёт льготы.
- **Мои дипломы.** Добавил свои дипломы — видишь все вузы и направления с льготами; в MAX дипломы хранятся в профиле.
- **Баллы.** Выбрал вуз и отметил ГТО, аттестат, волонтёрство — видишь, сколько баллов вуз добавит к ЕГЭ.
- **ИИ-помощник.** Рассказал, чем увлекаешься, — он подбирает олимпиады и вузы по базе льгот.

Данные — приёмная кампания 2026: 31 вуз (39 с филиалами), 659 направлений, 48 973 строки льгот,
173 олимпиады, 637 профилей. Источник — `data/Olimpiady_BVI_100ballov.xlsx` и документы приёмных
комиссий; данные справочные, перед подачей документов сверяйтесь с правилами приёма вуза.

```
Python 3.13 · FastAPI · SQLAlchemy/Alembic · PostgreSQL 17 · Redis · Dramatiq/RabbitMQ
Next.js 16 · React 19 · TanStack Query · OpenAPI-клиент · Tailwind 3 · Docker Compose · MAX Bridge
```

## Запуск

Нужен Docker. Одной командой:

```bash
docker compose up --build -d
```

Сайт — http://localhost:8080, API и Swagger — http://localhost:8000/docs. Первая сборка базы
занимает около минуты (`docker compose logs -f migrate`).

### Docker-образы

Проект собирается в два образа: `infra/Dockerfile.api` (API, сборка базы, воркеры, бот) и
`infra/Dockerfile.web` (сайт). Описание всех сервисов — `docker-compose.yml`.

```bash
# собрать образы
docker build -f infra/Dockerfile.api -t olymp-api .
docker build -f infra/Dockerfile.web -t olymp-web .
# или все образы проекта сразу
docker compose build

# запустить по шагам: база → миграции и сборка данных из XLSX → API и сайт
docker compose up -d postgres redis
docker compose run --rm migrate
docker compose up -d api web

# остановить и удалить контейнеры (данные базы остаются в томе pgdata)
docker compose down
```

### Пример запуска из командной строки

```bash
# пересобрать базу из data/Olimpiady_BVI_100ballov.xlsx и проверить качество данных
docker compose run --rm migrate olymp-ingest
docker compose run --rm migrate olymp-validate

# найти вузы, где «Высшая проба» даёт льготы
curl "http://localhost:8000/v1/search/by-olympiad?q=высшая%20проба"

# олимпиады, которые дают льготы на направление (id — из /v1/programs)
curl "http://localhost:8000/v1/search/by-program?program_id=130"
```

### Зависимости

Полный список Python-библиотек с версиями — [requirements.txt](requirements.txt). В разработке
зависимости ведёт `uv` (`pyproject.toml` + `uv.lock`); после их изменения `requirements.txt`
обновляется командой `uv export --all-packages --no-hashes --no-emit-workspace -o requirements.txt`.
Зависимости сайта — `package.json` и `package-lock.json`.

## Разработка

Нужны `uv`, Node.js 22+, Docker и `just` (без `just` команды из `justfile` можно запускать напрямую).

```bash
cp .env.example .env && uv sync --all-packages && npm install
just up && just seed      # PostgreSQL, Redis, RabbitMQ; миграции и сборка базы из XLSX
just api                  # API на :8000, Swagger — /docs
just web                  # сайт на :3000
```

| Что | Команда |
|---|---|
| Все проверки, как в CI | `just check` (= `just lint` + `just test`) |
| Проверка качества данных | `just validate` (`--check-links` — плюс ссылки по сети) |
| Обновить ссылки на документы вузов | `just refresh-sources` |
| После изменения эндпоинтов | `just openapi`: пересоздаёт `docs/openapi.json` и типы `packages/api-client` |
| Новая миграция БД | `just migration "описание"` |
| Весь стек в Docker (сайт :8080) | `just app` |

Тесты с базой пропускаются, если PostgreSQL не запущен: перед проверкой поднимите `just up`.

### Переменные окружения

| Переменная | По умолчанию | Что это |
|---|---|---|
| `OLYMP_DATABASE_URL` | `postgresql+psycopg://olymp:olymp@localhost:5432/olymp` | база данных |
| `OLYMP_REDIS_URL` | — | кэш и лимиты; без него — в памяти процесса |
| `OLYMP_RABBITMQ_URL` | — | очередь фоновых задач (Dramatiq) |
| `OLYMP_API_URL` | `http://127.0.0.1:8000` | куда сайт проксирует `/api/v1/*` |
| `OLYMP_MAX_BOT_TOKEN`, `OLYMP_MAX_BOT_NAME` | — | мини-приложение MAX (токен — секрет) |
| `OLYMP_LLM_BASE_URL`, `OLYMP_LLM_API_KEY`, `OLYMP_LLM_MODEL` | — | ИИ-помощник, любой OpenAI-совместимый провайдер; без них помощник выключен |
| `OLYMP_LLM_DAILY_REQUESTS` | 45 | обращений к модели в сутки на весь сервис; 0 — без ограничения |
| `OLYMP_WEB_PORT`, `OLYMP_API_PORT` | 8080, 8000 | порты Docker-стека |

Полный список — `.env.example`.

### Мини-приложение MAX

Сайт открывается в MAX как мини-приложение: API проверяет подпись данных запуска токеном бота и
хранит дипломы пользователя на сервере, вне MAX они хранятся в браузере. Бот (`olymp-max-bot`,
профиль `bot` в `docker-compose.yml`) ходит в `platform-api2.max.ru`, подписанный сертификатом
Минцифры: скачайте «Russian Trusted Root CA» с https://www.gosuslugi.ru/crt, положите файл
`*.pem`/`*.crt` в `infra/certs/` и запустите `docker compose --profile bot up -d`.

## Структура

| Папка | Что |
|---|---|
| `apps/api` | FastAPI, модульный монолит: каталог, поиск, «Мои дипломы», «Поделиться», баллы, ИИ-помощник |
| `apps/web` | Next.js: сайт и мини-приложение MAX |
| `apps/workers` | сборка базы из XLSX, обход сайтов вузов, проверки данных, бот MAX, фоновые задачи |
| `packages/domain` | чистая логика: нормализация названий, справочник олимпиад, условия дипломов |
| `packages/db` | модели SQLAlchemy и миграции Alembic — единственное место схемы БД |
| `packages/llm` | шлюз к языковым моделям для API и воркеров |
| `packages/api-client` | типы API для сайта, генерируются из `docs/openapi.json` |
| `infra` | Dockerfile'ы, окружение разработки, скрипты стенда |
| `data` | исходный XLSX, баллы за достижения, карточки олимпиад, ссылки на документы вузов |
| `scripts`, `design`, `presentation` | утилиты, макеты, презентация |

Правила кода: Python 3.13 (ruff, mypy `--strict`), TypeScript strict; схема БД меняется только
миграциями; контракт API — `docs/openapi.json`, он генерируется из FastAPI и руками не правится;
исходный XLSX не редактируется — исправления данных вносятся в код сборки с тестом.

## Стенд

`main` выкатывается на https://ideafix.patissons.tech после зелёного CI (workflow `deploy`, нужен
секрет `DEPLOY_SSH_KEY`). Ветки: `main` — стабильная версия, `dev` — разработка.
