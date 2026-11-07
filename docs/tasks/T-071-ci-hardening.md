---
id: T-071
title: Усилить CI: тесты без БД падают, одна голова Alembic, сборка Docker
status: todo
priority: P1
area: infra
estimate: M
spec: ""
depends: []
owner: ""
branch: ""
pr: ""
updated: 2026-11-07
---

## Цель
Сейчас тесты с базой в CI могут молча пропуститься; нет проверки миграций и образов.

## Что сделать
- [ ] OLYMP_REQUIRE_DB=1 в CI → отсутствие PostgreSQL = ошибка, а не skip
- [ ] Проверка одной головы Alembic; docker build api/web + смоук /healthz
- [ ] permissions: contents: read, кэш uv, dependabot для pip/npm/actions

## Критерии приёмки
- [ ] CI падает, если тесты с базой пропущены
- [ ] `just check` зелёный

## Контекст
По итогам ревью 2026-11-07.

## Журнал
