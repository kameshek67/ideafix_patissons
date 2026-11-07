---
id: T-022
title: Инструменты помощника поверх поиска
status: todo
priority: P0
area: api
estimate: M
spec: docs/specs/F-02-ai-chat.md
depends: [T-021]
owner: ""
branch: ""
pr: ""
updated: 2026-11-07
---

## Цель
Модель получает факты о льготах только из нашей базы.

## Что сделать
- [ ] find_olympiads, universities_for_olympiad, olympiads_for_program, match_diplomas, list_universities
- [ ] JSON-схемы инструментов, обрезка результатов (≤ 4 КБ), source_url в каждом результате
- [ ] Тесты каждого инструмента на собранной базе

## Критерии приёмки
- [ ] Каждый инструмент возвращает компактный JSON с источниками
- [ ] Ошибочные аргументы → понятная ошибка для модели, не 500
- [ ] `just check` зелёный

## Контекст
ТЗ: [F-02-ai-chat.md](../specs/F-02-ai-chat.md). Сервисы: modules/search/service.py, modules/achievements/service.py.

## Журнал
