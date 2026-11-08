# Как вносить изменения

Правила работы над «Олимпом»: команды, ветки, коммиты, PR и требования к коду. Если правило
расходится с кодом — прав код, исправь документ в том же PR.

## Команды

Нужны `uv`, Node.js 22+, Docker, `just`. Полный список — `just --list`.

| Что | Команда |
|---|---|
| Установить зависимости | `uv sync --all-packages && npm install` |
| Поднять PostgreSQL/Redis/RabbitMQ | `just up` |
| Миграции + сборка базы из XLSX | `just seed` |
| API (:8000, Swagger `/docs`) / сайт (:3000) | `just api` / `just web` |
| Все проверки как в CI | `just check` (= `just lint` + `just test` + `just tasks-check`) |
| После изменения эндпоинтов | `just openapi` и закоммитить `docs/openapi.json` + `packages/api-client/schema.d.ts` |
| Новая миграция | `just migration "описание"` (затем проверить сгенерированный файл руками) |
| Задачи: доска / следующие свободные | `just tasks` / `just tasks-next` |
| Весь стек в Docker (сайт :8080) | `just app` |

Тесты с базой сами пропускаются, если PostgreSQL не запущен — **пропуск не равен прохождению**:
перед PR подними `just up` или дождись зелёного CI.

## Ветки

```
main ──●──────────────●────────────●──────   только релизы (тег vX.Y.Z) и hotfix; автодеплой на ideafix.patissons.tech
        \            ↑ release PR   ↑ hotfix/*
dev  ────●──●──●──●──●──●──●──●──●──●──────   интеграция: сюда сливаются все задачи (squash)
            ↑  ↑     ↑
   feat/T-012-share  fix/T-020-…  docs/…        короткие ветки от dev, одна задача — одна ветка
```

| Ветка | От чего | Куда | Как сливается |
|---|---|---|---|
| `feat/T-NNN-коротко`, `fix/…`, `refactor/…`, `test/…` | `dev` | `dev` | squash |
| `docs/…`, `chore/…` (без задачи — только мелочи) | `dev` | `dev` | squash |
| `release/vX.Y.Z` — не используем, релиз = PR `dev → main` | — | `main` | merge commit |
| `hotfix/T-NNN-…` | `main` | `main`, затем `main → dev` | merge commit |

- В `main` и `dev` напрямую не пушим: только через PR, зелёный CI и одобрение человека.
- Ветка живёт не дольше 1–2 дней. Длинную задачу дроби на подзадачи.
- Перед ревью обнови ветку от `dev`: `git fetch && git rebase origin/dev` (или merge, если ветка общая).
- Архив прежних версий — теги `prototype-v1` (SQLite + JS), `archive/olymp-rebuild`
  (несостоявшаяся перестройка с LLM-конвейером), `archive/main-new-stack`.

## Коммиты

[Conventional Commits](https://www.conventionalcommits.org/ru/) с описанием на русском:

```
feat(web): кнопка «Поделиться» в карточке направления
fix(api): 404 вместо 500 для несуществующей олимпиады
docs(adr): 0010 — шлюз LLM
chore(tasks): взять T-012
```

Типы: `feat fix docs refactor test chore perf ci`. Области: `api web workers domain db infra docs tasks`.
В теле — «зачем», а не «что». Ссылка на задачу — `Refs: T-012`.


## Pull request

1. Заголовок: `T-012: Кнопка «Поделиться»` (для мелочей без задачи — как коммит).
2. Открывай **draft сразу после взятия задачи** — так видно, кто чем занят.
3. Заполни шаблон: что сделано, как проверено (команды и вывод), скриншоты для UI (телефон 390 px
   и десктоп), что не сделано.
4. Ready for review — когда выполнено «Определение готовности» ниже.
5. Ревью — минимум один человек из команды.

## Определение готовности (DoD)

- [ ] Выполнены критерии приёмки из файла задачи и ТЗ.
- [ ] `just check` зелёный локально (с поднятым `just up`) и CI зелёный.
- [ ] Новая логика покрыта тестами; тесты не ослаблены и не удалены ради зелёного CI.
- [ ] Схема БД — миграцией; контракт API — `just openapi` закоммичен.
- [ ] Документация обновлена: ТЗ, `docs/architecture/*`, ADR при новом решении.
- [ ] Нет секретов и персональных данных в коде, логах, тестах.
- [ ] UI проверен в узком окне (≈390 px) и, если затронут MAX, по ссылке `just max-link`.
- [ ] В файле задачи `status: review` и журнал заполнен.

## Релиз

1. PR `dev → main` с заголовком `Релиз vX.Y.Z`, в описании — список задач.
2. После слияния: `git tag vX.Y.Z main && git push origin vX.Y.Z`, задачи релиза → `status: done`.
3. Версии: `0.MINOR.PATCH` до сдачи хакатона; MINOR — новые фичи, PATCH — исправления.

Подробно — [docs/guides/release.md](docs/guides/release.md).

## Задачи и ТЗ

- Задачи — `docs/tasks/T-NNN-*.md`, протокол — [docs/tasks/README.md](docs/tasks/README.md).
- ТЗ фич — `docs/specs/F-NN-*.md`, шаблон — [docs/specs/TEMPLATE.md](docs/specs/TEMPLATE.md).
- Архитектурные решения — `docs/adr/NNNN-*.md`, шаблон — [docs/adr/0000-template.md](docs/adr/0000-template.md).

## Правила кода

- **Язык**: интерфейс, комментарии, docstring, сообщения коммитов и документация — на русском.
  Идентификаторы — на английском.
- **Python 3.13**: ruff (lint + format, строка 100), mypy `--strict` (кроме перенесённого кода
  прототипа, см. `pyproject.toml`), импорты абсолютные внутри пакета.
- **Границы модулей** (проверяет `lint-imports`): `olymp_domain` не знает про БД, API и воркеры;
  модули `olymp_api.modules.*` не импортируют друг друга (исключение — верхний слой `assistant`,
  он вызывает сервисы поиска); API не импортирует воркеры. Общий код модулей — в `olymp_api/*.py`
  (db, schemas, olympiads) или в `packages/domain`.
- **Схема БД** меняется только миграцией Alembic в `packages/db`. Таблицы с пользовательскими
  данными (`max_users`, `user_diplomas`, будущие) сборка базы (`olymp-ingest`) не трогает.
- **Контракт API** — `docs/openapi.json`, он генерируется из FastAPI. Фронтенд берёт типы только
  из `@olymp/api-client`; ручные типы для ответов API не заводим.
- **Ошибки API** — RFC 9457 (`application/problem+json`) через `olymp_api.errors`.
- **Фронтенд**: TypeScript strict; дизайн повторяет прототип — новые элементы собираются
  из существующих классов и токенов `apps/web/src/app/styles.css`, Tailwind 3.4.16 не обновлять.
  Всё, что зависит от MAX, работает и в обычном браузере (Bridge может отсутствовать).
- **Тесты** — рядом с кодом: `*/tests/test_*.py` (pytest), `*.test.ts(x)` (vitest). Новая логика
  без теста не принимается. Как писать — [docs/guides/testing.md](docs/guides/testing.md).

Правила для отдельных сервисов — в их README: [API](apps/api/README.md#правила-разработки),
[сайт](apps/web/README.md#правила-разработки), [воркеры](apps/workers/README.md#правила-разработки).

## Нельзя

- Коммитить секреты (`.env`, токен бота MAX, ключи LLM) и персональные данные. CI гоняет gitleaks.
- Редактировать руками сгенерированное: `docs/openapi.json`, `packages/api-client/schema.d.ts`,
  `uv.lock`/`package-lock.json` (только через uv/npm).
- Редактировать `data/Olimpiady_BVI_100ballov.xlsx` — это исходник; исправления данных — в коде
  сборки с тестом.
- Отправлять в LLM персональные данные (имя, id пользователя MAX) и исполнять инструкции из
  текста документов вузов или ответов LLM — это недоверенные данные.
- Менять пороги качества, удалять или ослаблять тесты, чтобы CI стал зелёным.
- Трогать теги `prototype-v1`, `archive/*` — это архив прежних версий.
