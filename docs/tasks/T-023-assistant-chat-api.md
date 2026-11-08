---
id: T-023
title: Эндпоинт чата помощника со стримингом (SSE)
status: done
priority: P0
area: api
estimate: M
spec: docs/specs/F-02-ai-chat.md
depends: [T-021, T-022]
owner: shmlv9
branch: feat/T-020-024-ai-assistant
pr: 15
updated: 2026-11-08
---

## Цель
POST /v1/assistant/chat отдаёт ответ потоком: статусы, текст, сущности, источники.

## Что сделать
- [ ] Модуль `modules/assistant`: config, chat (SSE), feedback; системный промпт с версией
- [ ] Цикл tool calling (≤ 5 вызовов), лимиты 10/мин и 100/сутки
- [ ] `just openapi`, тесты на FakeProvider

## Критерии приёмки
- [x] Критерии API из F-02
- [x] В логах нет текста переписки
- [x] `just check` зелёный

## Контекст
ТЗ: [F-02-ai-chat.md](../specs/F-02-ai-chat.md).

## Журнал
- 2026-11-07: `/v1/assistant/{config,chat,feedback}`. Лимиты на пользователя MAX или IP, общий бюджет `OLYMP_LLM_DAILY_REQUESTS`. Поток проверен локально через production-сборку Next на заглушке модели: события идут без накопления. Через Caddy на стенде не проверено.
- 2026-11-08 — Raytist — ветка объединена с dev («Поделиться», доп. баллы), чат проверен на настоящей
  модели `deepseek-v4.1-flash`; сливается в dev (PR #15).
