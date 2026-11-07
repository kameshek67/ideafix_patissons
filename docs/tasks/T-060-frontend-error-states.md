---
id: T-060
title: Обработать ошибки загрузки: «Не получилось загрузить» и «Повторить»
status: todo
priority: P0
area: web
estimate: S
spec: ""
depends: []
owner: ""
branch: ""
pr: ""
updated: 2026-11-07
---

## Цель
Сейчас при ошибке API экран навсегда остаётся на скелетоне, а тексты ошибок написаны для разработчика.

## Что сделать
- [ ] try/catch и состояние «ошибка» в OlympApp.tsx (pickProgram, openProgram, runOlympiadSearch, pickResultUniversity, suggest), Combo.refresh, подсказках DiplomaSheet
- [ ] api.ts: брать title/detail из problem+json; тексты для школьника, без «бэкенд» и «olymp-ingest»
- [ ] Компонентный тест: API отвечает 500 → видна ошибка и кнопка «Повторить»

## Критерии приёмки
- [ ] Ни один сценарий не зависает на скелетоне при ошибке сети или 5xx
- [ ] `just check` зелёный

## Контекст
По итогам ревью 2026-11-07.

## Журнал
