---
id: T-023
title: Эндпоинт чата помощника со стримингом (SSE)
status: todo
priority: P0
area: api
estimate: M
spec: docs/specs/F-02-ai-chat.md
depends: [T-021, T-022]
owner: ""
branch: ""
pr: ""
updated: 2026-11-07
---

## Цель
POST /v1/assistant/chat отдаёт ответ потоком: статусы, текст, сущности, источники.

## Что сделать
- [ ] Модуль `modules/assistant`: config, chat (SSE), feedback; системный промпт с версией
- [ ] Цикл tool calling (≤ 5 вызовов), лимиты 10/мин и 100/сутки
- [ ] `just openapi`, тесты на FakeProvider

## Критерии приёмки
- [ ] Критерии API из F-02
- [ ] В логах нет текста переписки
- [ ] `just check` зелёный

## Контекст
ТЗ: [F-02-ai-chat.md](../specs/F-02-ai-chat.md).

## Журнал
