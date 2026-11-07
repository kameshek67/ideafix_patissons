# Олимп — куда поступить по олимпиаде

Сервис и мини-приложение мессенджера **MAX**, которое отвечает школьнику, где его олимпиадный
диплом даёт **БВИ** (поступление без экзаменов) или **100 баллов** за ЕГЭ. Учитываются условия
вуза: степень диплома, класс, год, профиль. У каждой льготы есть ссылка на документ приёмной комиссии.

- **Вуз → олимпиады.** Выбрал вуз и направление — видишь, какие олимпиады дают льготы и что нужно подтвердить ЕГЭ.
- **Олимпиада → вузы.** Ввёл «вышка», «всош» или «пвг» — видишь все вузы, где она даёт льготы.
- **Мои дипломы.** Добавил свои дипломы — видишь все вузы и направления с льготами; в MAX дипломы хранятся в профиле.

Данные — приёмная кампания 2026: 31 вуз (39 с филиалами), 659 направлений, 48 963 строки льгот,
173 олимпиады, 635 профилей.

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
| Что сделано по версиям | [CHANGELOG.md](CHANGELOG.md) |
| Вся документация | [docs/README.md](docs/README.md) |

## Ветки

`main` — стабильная версия для демо, `dev` — разработка. Работа идёт в ветках от `dev` через PR
([CONTRIBUTING.md](CONTRIBUTING.md)). Прежние версии: тег `prototype-v1` (прототип на SQLite и JS),
`archive/olymp-rebuild` (эксперимент с LLM-конвейером).

## Структура

```
apps/api          FastAPI: каталог, поиск, «Мои дипломы», вход через MAX
apps/web          Next.js: сайт и мини-приложение MAX
apps/workers      сборка базы из XLSX, обход сайтов вузов, проверки данных, бот MAX
packages/domain   чистая логика: нормализация названий, условия дипломов
packages/db       модели и миграции
packages/api-client  типы API (генерируются из docs/openapi.json)
data/             исходный XLSX и ссылки на документы вузов
docs/             документация, ТЗ, ADR, задачи
infra/            Dockerfile'ы и окружение для разработки
```

Данные справочные: перед подачей документов сверяйтесь с правилами приёма вуза.
