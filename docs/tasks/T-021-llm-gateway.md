---
id: T-021
title: Шлюз LLM в API (OpenAI-совместимый, с поддельным провайдером)
status: todo
priority: P0
area: api
estimate: M
spec: docs/specs/F-02-ai-chat.md
depends: []
owner: ""
branch: ""
pr: ""
updated: 2026-11-07
---

## Цель
Единая точка вызова LLM с таймаутами, ретраями, бюджетом и тестовым двойником (ADR 0010).

## Что сделать
- [ ] `olymp_api/llm/`: настройки OLYMP_LLM_*, клиент (httpx, chat.completions + tools + stream), fallback-модель
- [ ] FakeProvider для тестов (скриптуемые ответы и вызовы инструментов)
- [ ] Решить, как инструменты зовут поиск, не нарушая границ модулей (общий слой или внутренний ASGI) — записать в ТЗ

## Критерии приёмки
- [ ] Тесты шлюза на FakeProvider
- [ ] Без OLYMP_LLM_API_KEY/BASE_URL шлюз выключен, приложение работает
- [ ] `just check` зелёный

## Контекст
ТЗ: [F-02-ai-chat.md](../specs/F-02-ai-chat.md). Не логировать текст запросов. Никаких ПДн в запросах.

## Журнал
