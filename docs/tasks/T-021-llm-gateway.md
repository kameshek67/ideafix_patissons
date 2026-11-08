---
id: T-021
title: Шлюз LLM в API (OpenAI-совместимый, с поддельным провайдером)
status: done
priority: P0
area: api
estimate: M
spec: docs/specs/F-02-ai-chat.md
depends: [T-073]
owner: shmlv9
branch: feat/T-020-024-ai-assistant
pr: 15
updated: 2026-11-08
---

## Цель
Единая точка вызова LLM с таймаутами, ретраями, бюджетом и тестовым двойником (ADR 0010).

## Что сделать
- [ ] `olymp_api/llm/`: настройки OLYMP_LLM_*, клиент (httpx, chat.completions + tools + stream), fallback-модель
- [ ] FakeProvider для тестов (скриптуемые ответы и вызовы инструментов)
- [ ] Решить, как инструменты зовут поиск, не нарушая границ модулей (общий слой или внутренний ASGI) — записать в ТЗ

## Критерии приёмки
- [x] Тесты шлюза на FakeProvider
- [x] Без OLYMP_LLM_API_KEY/BASE_URL шлюз выключен, приложение работает
- [x] `just check` зелёный

## Контекст
ТЗ: [F-02-ai-chat.md](../specs/F-02-ai-chat.md). Не логировать текст запросов. Никаких ПДн в запросах.

## Журнал
- 2026-11-07: `olymp_api/llm`, FakeProvider, маскирование `olymp_domain.pii`. Инструменты вызывают сервисы напрямую: `assistant` — верхний слой, контракт `layers` в pyproject.toml (записано в ТЗ и ADR 0010). Зависимость T-073 закрыта правкой только части F-02.
- 2026-11-08 — Raytist — ветка объединена с dev («Поделиться», доп. баллы), чат проверен на настоящей
  модели `deepseek-v4.1-flash`; сливается в dev (PR #15).
