---
id: T-004
title: Хуки перед коммитом: ruff, format, tsc, проверка задач
status: todo
priority: P1
area: infra
estimate: S
spec: ""
depends: [T-001]
owner: ""
branch: ""
pr: ""
updated: 2026-11-07
---

## Цель
Ошибки линтера видны до пуша, а не в CI.

## Что сделать
- [ ] lefthook (npm devDependency) или pre-commit: ruff check --fix, ruff format, tsc на изменённых, tasks.py check
- [ ] Инструкция в docs/guides/development.md; хуки ставятся `npm install`

## Критерии приёмки
- [ ] Коммит с ошибкой ruff отклоняется локально
- [ ] Хуки работают в Git Bash на Windows
- [ ] `just check` зелёный

## Контекст
—

## Журнал
