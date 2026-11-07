---
id: T-012
title: Кнопка «Поделиться» и отправка в MAX / браузере
status: todo
priority: P0
area: web
estimate: M
spec: docs/specs/F-01-share.md
depends: [T-011, T-062]
owner: ""
branch: ""
pr: ""
updated: 2026-11-07
---

## Цель
Школьник отправляет карточку направления, выдачу по олимпиаде или итоги дипломов в чат.

## Что сделать
- [ ] `lib/share.ts`: buildShareText, shareVia(app) — MAX shareMaxContent → navigator.share → буфер; тесты
- [ ] Кнопка в ProgramView, OlympiadResults/UniversityBenefits, DiplomasView (стили прототипа)
- [ ] Тост «Ссылка скопирована», haptic success

## Критерии приёмки
- [ ] В браузере ссылка копируется или открывается системное меню
- [ ] В MAX открывается выбор чата
- [ ] `just check` зелёный

## Контекст
ТЗ: [F-01-share.md](../specs/F-01-share.md). lib/max.ts (shareMaxContent уже типизирован), MaxProvider. До готовности T-011 — мок API.

## Журнал
