---
id: T-060
title: Обработать ошибки загрузки: «Не получилось загрузить» и «Повторить»
status: review
priority: P0
area: web
estimate: S
spec: ""
depends: []
owner: 34elo
branch: feat/T-060-error-states
pr: ""
updated: 2026-11-07
---

## Цель
Сейчас при ошибке API экран навсегда остаётся на скелетоне, а тексты ошибок написаны для разработчика.

## Что сделать
- [x] try/catch и состояние «ошибка» в OlympApp.tsx (pickProgram, openProgram, runOlympiadSearch, pickResultUniversity, suggest), Combo.refresh, подсказках DiplomaSheet
- [x] api.ts: брать title/detail из problem+json; тексты для школьника, без «бэкенд» и «olymp-ingest»
- [x] Компонентный тест: API отвечает 500 → видна ошибка и кнопка «Повторить»

## Критерии приёмки
- [x] Ни один сценарий не зависает на скелетоне при ошибке сети или 5xx
- [ ] `just check` зелёный

## Контекст
По итогам ревью 2026-11-07.

## Журнал

- 2026-11-08: общий `LoadError` с «Повторить»; `ApiError` со статусом и `friendlyError` (5xx / 4xx / нет связи) вместо «404 Not Found»; ошибки в pickProgram, openProgram, runOlympiadSearch, pickResultUniversity, Combo и справочниках; сбой подсказок поиска молча скрывает их. DiplomaSheet уже обрабатывал ошибки (`formError`). Вместо title/detail из problem+json — три готовых текста: тело ответа школьнику не нужно. Тесты: `ErrorStates.test.tsx`.
