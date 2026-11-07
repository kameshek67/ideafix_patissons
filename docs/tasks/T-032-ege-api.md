---
id: T-032
title: Параметр ege в /v1/achievements/match и хранение баллов в профиле
status: todo
priority: P0
area: api
estimate: M
spec: docs/specs/F-03-ege-check.md
depends: [T-031]
owner: ""
branch: ""
pr: ""
updated: 2026-11-07
---

## Цель
API считает статус подтверждения льготы баллами ЕГЭ.

## Что сделать
- [ ] ege=inf:82 (повторяемый), ege_status/ege_gap в строках, счётчики в итогах; без ege — как раньше
- [ ] Миграция user_ege_scores, PUT/GET /v1/me/diplomas с ege и ege_is_mock
- [ ] `just openapi`, тесты

## Критерии приёмки
- [ ] Критерии API из F-03
- [ ] Старые клиенты без ege получают прежний ответ
- [ ] `just check` зелёный

## Контекст
ТЗ: [F-03-ege-check.md](../specs/F-03-ege-check.md).

## Журнал
