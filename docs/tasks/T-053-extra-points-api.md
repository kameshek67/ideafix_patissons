---
id: T-053
title: API: баллы за достижения в подборе по вузам
status: done
priority: P3
area: api
estimate: M
spec: docs/specs/F-05-extra-points.md
depends: [T-052]
owner: 34elo
branch: feat/T-050-054-extra-points-v2
pr: 17
updated: 2026-11-07
---

## Цель
Школьник видит, сколько баллов добавят его достижения в каждом вузе.

## Что сделать
- [x] GET /v1/achievements/extra?kind=medal&kind=gto_gold — баллы по вузам с учётом лимита вуза (общий лимит суммы ИД — по правилам приёма, проверить в T-050)
- [ ] Хранение отмеченных достижений в профиле MAX (рядом с дипломами); без MAX — на устройстве
- [ ] `just openapi`, тесты

## Критерии приёмки
- [x] Сумма баллов не превышает лимит вуза
- [x] Тесты на собранной базе
- [ ] `just check` зелёный

## Контекст
ТЗ: [F-05-extra-points.md](../specs/F-05-extra-points.md). Приоритет P3 — сроки решает команда (см. docs/specs/BACKLOG.md).

## Журнал

- 2026-11-07: вместо GET по видам — `POST /v1/extra-points/score` (достижения передаются телом, ничего не сохраняется) плюс `GET /v1/extra-points/universities[/{id}]`. Не сделано: хранение отмеченного в профиле MAX и `just openapi` (docs/openapi.json и schema.d.ts не обновлены).
