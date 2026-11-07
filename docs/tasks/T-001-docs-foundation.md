---
id: T-001
title: Документация, правила разработки, система задач
status: review
priority: P0
area: docs
estimate: L
spec: ""
depends: []
owner: 34elo
branch: docs/foundation
pr: ""
updated: 2026-11-07
---

## Цель
Чтобы новый участник за 10 минут понял проект и процесс: CONTRIBUTING, docs/ (архитектура, ADR, ТЗ продукта, ТЗ фич), задачи и скрипт, шаблоны PR, CI на dev.

## Что сделать
- [ ] CONTRIBUTING.md, README сервисов, короткий README
- [ ] docs/architecture/*, docs/adr/0001–0010, docs/product/*, docs/guides/*, docs/runbooks/*
- [ ] docs/specs/F-01…F-05, docs/tasks/* и scripts/tasks.py, рецепты just
- [ ] .github: шаблоны PR и issue, CI на dev и проверка задач

## Критерии приёмки
- [ ] `just tasks-check` и `just check` зелёные
- [ ] Все ссылки в docs/ ведут на существующие файлы
- [ ] README помещается в один экран: что это, как запустить, где документация
- [ ] `just check` зелёный

## Контекст
Ветка `docs/foundation`. Исходный README разнесён по docs/architecture/*.

## Журнал
- 2026-11-07 — 34elo — main перемотан на feature/my-diplomas, создан dev, архивные теги; написана документация
