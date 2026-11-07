---
id: T-075
title: Мелкие баги API: регистр поиска направлений, N+1, гонка сохранения дипломов
status: todo
priority: P2
area: api
estimate: M
spec: ""
depends: []
owner: ""
branch: ""
pr: ""
updated: 2026-11-07
---

## Цель
Найдено в ревью кода; каждое — небольшое, но заметное.

## Что сделать
- [ ] Поиск направлений без учёта регистра (LIKE при COLLATE C, catalog/service.py) — проверить и исправить
- [ ] N+1 в by_olympiad; уникальный индекс olympiads.squash_key
- [ ] Гонка DELETE+INSERT в PUT /v1/me/diplomas (500 при двух устройствах); повтор сохранения в useMyDiplomas

## Критерии приёмки
- [ ] Тесты на каждый случай
- [ ] `just check` зелёный

## Контекст
По итогам ревью 2026-11-07.

## Журнал
