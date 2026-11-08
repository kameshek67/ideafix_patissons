# Документация «Олимпа»

## С чего начать

| Кто ты | Читай по порядку |
|---|---|
| Новый в команде | [README](../README.md) → [architecture/overview.md](architecture/overview.md) → [guides/development.md](guides/development.md) → [CONTRIBUTING.md](../CONTRIBUTING.md) |
| Берёшь задачу | `just tasks-next` → файл задачи → ТЗ из поля `spec` → [tasks/README.md](tasks/README.md) (как взять) |
| Думаешь о продукте / питче | [product/spec.md](product/spec.md) → [specs/BACKLOG.md](specs/BACKLOG.md) |
| Жюри / внешний читатель | [README](../README.md) → [product/spec.md](product/spec.md) → [architecture/overview.md](architecture/overview.md) → [adr/](adr/README.md) |

## Разделы

| Раздел | Что внутри |
|---|---|
| [product/](product/spec.md) | ТЗ продукта, [глоссарий](product/glossary.md) (БВИ, РСОШ, профиль…), [ограничения](product/limitations.md) |
| [specs/](specs/README.md) | ТЗ фич F-01…F-05 и [бэклог](specs/BACKLOG.md) всех идей |
| [tasks/](tasks/README.md) | задачи `T-*.md`, [дорожная карта](tasks/ROADMAP.md), протокол взятия задачи |
| [architecture/](architecture/overview.md) | [обзор](architecture/overview.md), [стек](architecture/stack.md), [данные](architecture/data.md), [API](architecture/api.md), [фронтенд](architecture/frontend.md), [MAX](architecture/max-mini-app.md) |
| [adr/](adr/README.md) | архитектурные решения и их причины |
| [guides/](guides/development.md) | [разработка](guides/development.md), [тесты](guides/testing.md), [релиз](guides/release.md) |
| [runbooks/](runbooks/deploy.md) | [деплой и стенд](runbooks/deploy.md), [MAX](runbooks/max-setup.md), [обновление данных](runbooks/data-refresh.md) |
| `openapi.json` | контракт API — генерируется `just openapi`, руками не править |

## Сервисы и пакеты

| Где | Что | README |
|---|---|---|
| `apps/api` | FastAPI: каталог, поиск, «Мои дипломы», вход через MAX | [README](../apps/api/README.md) |
| `apps/web` | Next.js: сайт и мини-приложение MAX | [README](../apps/web/README.md) |
| `apps/workers` | сборка базы, обход сайтов вузов, проверки, бот MAX | [README](../apps/workers/README.md) |
| `packages/domain` | чистая логика: названия олимпиад, условия дипломов | [README](../packages/domain/README.md) |
| `packages/db` | модели и миграции | [README](../packages/db/README.md) |
| `packages/llm` | шлюз к языковым моделям для API и воркеров | [README](../packages/llm/README.md) |
| `packages/api-client` | типы API для сайта (генерируются) | [README](../packages/api-client/README.md) |
| `infra` | Docker, окружение разработки, стенд | [README](../infra/README.md) |
| `scripts`, `data`, `design`, `presentation` | утилиты, исходные данные, макеты, презентация | [scripts](../scripts/README.md) · [data](../data/README.md) · [design](../design/README.md) · [presentation](../presentation/README.md) |

Правило: одна тема — один файл; факты, которые меняются вместе с кодом, обновляются в том же PR.
