---
id: T-010
title: Стабильный ключ направления при сборке базы
status: todo
priority: P0
area: workers
estimate: S
spec: docs/specs/F-01-share.md
depends: []
owner: ""
branch: ""
pr: ""
updated: 2026-11-07
---

## Цель
Ссылки «Поделиться» на направление должны переживать пересборку базы (ADR 0007).

## Что сделать
- [ ] Функция `program_stable_key(university_short, name, codes)` в packages/domain + тесты
- [ ] Миграция: `programs.stable_key text` + уникальный индекс
- [ ] Заполнение в olymp-ingest; тест: ключи уникальны и совпадают между двумя сборками

## Критерии приёмки
- [ ] Две сборки подряд дают одинаковые stable_key
- [ ] Ключи уникальны на настоящих данных
- [ ] `just check` зелёный

## Контекст
ТЗ: [F-01-share.md](../specs/F-01-share.md). apps/workers/src/olymp_workers/ingest.py (ProgramRegistry), packages/db/models.py.

## Журнал
