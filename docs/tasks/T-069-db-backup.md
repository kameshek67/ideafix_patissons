---
id: T-069
title: Бэкапы: копия дампов стенда вне сервера и just backup / restore локально
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
На стенде дампы делаются ежедневно, но лежат на том же сервере (infra/deploy/README.md). Нужна копия в другом месте и такие же рецепты локально.

## Что сделать
- [ ] Копировать /var/backups/ideafix за пределы сервера
- [ ] Рецепты just backup (pg_dump в backups/, в .gitignore) и restore
- [ ] Шаг в docs/guides/release.md и runbooks/deploy.md

## Критерии приёмки
- [ ] Восстановление из бэкапа проверено на локальном стеке
- [ ] `just check` зелёный

## Контекст
По итогам ревью 2026-11-07.

## Журнал
