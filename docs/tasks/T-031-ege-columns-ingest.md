---
id: T-031
title: Колонки confirm_subjects / min_ege_score при сборке
status: todo
priority: P0
area: workers
estimate: S
spec: docs/specs/F-03-ege-check.md
depends: [T-030]
owner: ""
branch: ""
pr: ""
updated: 2026-11-07
---

## Цель
Числовой порог и коды предметов в базе для быстрых проверок.

## Что сделать
- [ ] Миграция benefits: confirm_subjects text[], min_ege_score smallint
- [ ] Заполнение в olymp-ingest, тест итоговых чисел

## Критерии приёмки
- [ ] Колонки заполнены, тест сборки зелёный
- [ ] `just check` зелёный

## Контекст
ТЗ: [F-03-ege-check.md](../specs/F-03-ege-check.md).

## Журнал
