---
id: T-069
title: Бэкап и восстановление БД: just backup / just restore
status: todo
priority: P1
area: infra
estimate: S
spec: ""
depends: []
owner: ""
branch: ""
pr: ""
updated: 2026-11-07
---

## Цель
Перед демо и релизом нужна возможность откатить данные пользователей.

## Что сделать
- [ ] Рецепты just backup (pg_dump в backups/, в .gitignore) и restore
- [ ] Шаг в docs/guides/release.md и runbooks/deploy.md

## Критерии приёмки
- [ ] Восстановление из бэкапа проверено на локальном стеке
- [ ] `just check` зелёный

## Контекст
По итогам ревью 2026-11-07.

## Журнал
