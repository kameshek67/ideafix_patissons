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
173 олимпиады, 637 профилей.

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

Для разработки (нужны uv, Node.js 22+, Docker, just):

```bash
cp .env.example .env && uv sync --all-packages && npm install
just up && just seed      # инфраструктура и база
just api                  # :8000
just web                  # :3000
```

Подробно, а также Windows без just — [docs/guides/development.md](docs/guides/development.md).
Мини-приложение в MAX — [docs/runbooks/max-setup.md](docs/runbooks/max-setup.md).

## Стенд

`main` выкатывается на https://ideafix.patissons.tech сам, после зелёного `ci`. HTTPS там даёт
Caddy сервера, профили `https` и `tunnel` не нужны. Токен бота MAX и другие секреты стенда лежат
в `/opt/ideafix/shared/.env` на сервере. Как это устроено и как откатиться —
[infra/deploy/README.md](infra/deploy/README.md).

## Документация

| | |
|---|---|
| Как всё устроено | [docs/architecture/overview.md](docs/architecture/overview.md) |
| ТЗ продукта и фич | [docs/product/spec.md](docs/product/spec.md), [docs/specs/](docs/specs/README.md) |
| Архитектурные решения | [docs/adr/](docs/adr/README.md) |
| Задачи и план | [docs/tasks/ROADMAP.md](docs/tasks/ROADMAP.md), `just tasks` |
| Как вносить изменения | [CONTRIBUTING.md](CONTRIBUTING.md) |
| Вся документация | [docs/README.md](docs/README.md) |

## Ветки

`main` — стабильная версия для демо, `dev` — разработка. Работа идёт в ветках от `dev` через PR
([CONTRIBUTING.md](CONTRIBUTING.md)). Прежние версии: тег `prototype-v1` (прототип на SQLite и JS),
`archive/olymp-rebuild` (эксперимент с LLM-конвейером).

## Структура

| Папка | Что | |
|---|---|---|
| `apps/api` | FastAPI: каталог, поиск, «Мои дипломы», вход через MAX | [README](apps/api/README.md) |
| `apps/web` | Next.js: сайт и мини-приложение MAX | [README](apps/web/README.md) |
| `apps/workers` | сборка базы из XLSX, обход сайтов вузов, проверки данных, бот MAX | [README](apps/workers/README.md) |
| `packages/domain` | чистая логика: нормализация названий, условия дипломов | [README](packages/domain/README.md) |
| `packages/db` | модели и миграции | [README](packages/db/README.md) |
| `packages/api-client` | типы API (генерируются из `docs/openapi.json`) | [README](packages/api-client/README.md) |
| `infra` | Docker, окружение разработки, стенд | [README](infra/README.md) |
| `data`, `scripts` | исходный XLSX и ссылки на документы; утилиты | [data](data/README.md) · [scripts](scripts/README.md) |
| `docs` | документация, ТЗ, ADR, задачи, ревью | [README](docs/README.md) |

Данные справочные: перед подачей документов сверяйтесь с правилами приёма вуза.
