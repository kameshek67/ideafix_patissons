---
id: T-071
title: "Усилить CI: тесты без БД падают, одна голова Alembic, сборка Docker"
status: done
priority: P1
area: infra
estimate: M
spec: ""
depends: []
owner: 34elo
branch: chore/T-071-ci-hardening
pr: 64
updated: 2026-11-08
---

## Цель
Сейчас тесты с базой в CI могут молча пропуститься; нет проверки миграций и образов.

## Что сделать
- [x] OLYMP_REQUIRE_DB=1 в CI → отсутствие PostgreSQL = ошибка, а не skip
- [x] Проверка одной головы Alembic и `alembic check`; docker build api/web + смоук /healthz
- [x] permissions: contents: read, кэш uv, dependabot для uv/npm/actions (в dev, раз в неделю)

## Критерии приёмки
- [x] CI падает, если тесты с базой пропущены (проверено локально: 5 errors вместо 5 skipped)
- [x] `just check` зелёный (CI)

## Контекст
По итогам ревью 2026-11-07.

## Журнал
- 2026-11-08 — 34elo — сделано; сборка образов проверяется на самом PR.
