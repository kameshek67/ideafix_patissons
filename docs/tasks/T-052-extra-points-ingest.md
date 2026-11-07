---
id: T-052
title: Модель и сборка ИД: таблица individual_achievements
status: todo
priority: P3
area: workers
estimate: S
spec: docs/specs/F-05-extra-points.md
depends: [T-051]
owner: ""
branch: ""
pr: ""
updated: 2026-11-07
---

## Цель
Данные об ИД попадают в базу вместе с остальными при сборке.

## Что сделать
- [ ] Миграция: individual_achievements(university_id, kind, points, conditions, source_url)
- [ ] Загрузка CSV в olymp-ingest (та же транзакция), проверка в olymp-validate
- [ ] Тест: число строк и вузов после сборки

## Критерии приёмки
- [ ] Сборка детерминирована, тест итоговых чисел обновлён осознанно
- [ ] `just check` зелёный

## Контекст
ТЗ: [F-05-extra-points.md](../specs/F-05-extra-points.md). Приоритет P3 — сроки решает команда (см. docs/specs/BACKLOG.md).

## Журнал
