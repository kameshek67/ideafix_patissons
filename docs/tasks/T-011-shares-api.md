---
id: T-011
title: API снимков для ссылок «Поделиться» (/v1/shares)
status: todo
priority: P0
area: api
estimate: M
spec: docs/specs/F-01-share.md
depends: [T-010]
owner: ""
branch: ""
pr: ""
updated: 2026-11-07
---

## Цель
Короткая стабильная ссылка на направление, выдачу по олимпиаде или итоги дипломов.

## Что сделать
- [ ] Миграция `share_links`; модуль `modules/sharing` (router, schemas, service) + контракт import-linter
- [ ] POST /v1/shares (идемпотентно по хэшу, лимит 30/мин), GET /v1/shares/{token} с `resolved`
- [ ] `just openapi`, тесты (в т.ч. токен переживает пересборку)

## Критерии приёмки
- [ ] Критерии API из F-01 выполнены
- [ ] Пересборка базы не трогает share_links
- [ ] `just check` зелёный

## Контекст
ТЗ: [F-01-share.md](../specs/F-01-share.md). Похожий модуль — modules/achievements. Ошибки — olymp_api.errors.

## Журнал
