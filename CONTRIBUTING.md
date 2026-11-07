# Как вносить изменения

Правила работы над «Олимпом»: ветки, коммиты, PR и требования к коду.

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
