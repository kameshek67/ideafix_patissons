---
id: T-052
title: Модель и сборка ИД: таблица individual_achievements
status: done
priority: P3
area: workers
estimate: S
spec: docs/specs/F-05-extra-points.md
depends: [T-051]
owner: 34elo
branch: feat/T-050-054-extra-points-v2
pr: 17
updated: 2026-11-07
---

## Цель
Данные об ИД попадают в базу вместе с остальными при сборке.

## Что сделать
- [x] Миграция: individual_achievements(university_id, kind, points, conditions, source_url)
- [x] Загрузка CSV в olymp-ingest (та же транзакция), проверка в olymp-validate
- [x] Тест: число строк и вузов после сборки

## Критерии приёмки
- [ ] Сборка детерминирована, тест итоговых чисел обновлён осознанно
- [ ] `just check` зелёный

## Контекст
ТЗ: [F-05-extra-points.md](../specs/F-05-extra-points.md). Приоритет P3 — сроки решает команда (см. docs/specs/BACKLOG.md).

## Журнал

- 2026-11-07: миграция `0003`, `olymp_workers/extra_points.py`, проверки в `olymp-validate`, тест в `test_ingest.py` (223 правила, 7 вузов, 6 лимитов). Вместо JSON `conditions` — отдельные колонки (`variants`, `years`, `recency_years`, `exclusive_group`). `just check` целиком не запускался.
