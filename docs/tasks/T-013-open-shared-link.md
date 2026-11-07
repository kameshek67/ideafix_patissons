---
id: T-013
title: Открытие ссылок s_<token> и /s/<token>
status: done
priority: P0
area: web
estimate: S
spec: docs/specs/F-01-share.md
depends: [T-011, T-062]
owner: Raytist
branch: feat/T-012-share
pr: 14
updated: 2026-11-07
---

## Цель
Получатель ссылки попадает на тот же экран в MAX и в браузере.

## Что сделать
- [x] Маршрут app/s/[token] (noindex, Referrer-Policy: no-referrer) → OlympApp с токеном
- [x] Обработка start_param `s_<token>` рядом с существующими program-/olympiad-/diplomas (`parseStartParam`)
- [x] Режим «чужие дипломы — только чтение» в DiplomasView; тост «Ссылка устарела»

## Критерии приёмки
- [x] Ссылка открывает тот же экран
- [x] Свои дипломы получателя не меняются
- [x] Старые startapp работают
- [x] `just check` зелёный

## Контекст
ТЗ: [F-01-share.md](../specs/F-01-share.md). OlympApp.tsx, блок «запуск по ссылке».

## Журнал
- 2026-11-07 — Raytist — получатель видит экран с фильтром отправителя; олимпиада открывается сразу на
  экране вуза, если им делились. Чужие дипломы — отдельное состояние OlympApp, в localStorage
  и профиль MAX не пишутся; «Проверить свои дипломы» возвращает к своим и меняет адрес на «/».
  Онбординг по ссылке /s/ не показывается. Картинки — абсолютными путями (/assets/…).
- 2026-11-07 — Raytist — PR #14 сливается в `dev` (squash), CI зелёный.
