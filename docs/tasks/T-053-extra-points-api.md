---
id: T-053
title: API: баллы за достижения в подборе по вузам
status: todo
priority: P3
area: api
estimate: M
spec: docs/specs/F-05-extra-points.md
depends: [T-052]
owner: ""
branch: ""
pr: ""
updated: 2026-11-07
---

## Цель
Школьник видит, сколько баллов добавят его достижения в каждом вузе.

## Что сделать
- [ ] GET /v1/achievements/extra?kind=medal&kind=gto_gold — баллы по вузам с учётом лимита вуза (общий лимит суммы ИД — по правилам приёма, проверить в T-050)
- [ ] Хранение отмеченных достижений в профиле MAX (рядом с дипломами); без MAX — на устройстве
- [ ] `just openapi`, тесты

## Критерии приёмки
- [ ] Сумма баллов не превышает лимит вуза
- [ ] Тесты на собранной базе
- [ ] `just check` зелёный

## Контекст
ТЗ: [F-05-extra-points.md](../specs/F-05-extra-points.md). Приоритет P3 — сроки решает команда (см. docs/specs/BACKLOG.md).

## Журнал
