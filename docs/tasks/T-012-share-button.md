---
id: T-012
title: Кнопка «Поделиться» и отправка в MAX / браузере
status: done
priority: P0
area: web
estimate: M
spec: docs/specs/F-01-share.md
depends: [T-011, T-062]
owner: Raytist
branch: feat/T-012-share
pr: 14
updated: 2026-11-07
---

## Цель
Школьник отправляет карточку направления, выдачу по олимпиаде или итоги дипломов в чат.

## Что сделать
- [x] `lib/share.ts`: тексты по видам экранов, `sendShare(app)` — MAX shareMaxContent → shareContent → navigator.share → буфер; тесты
- [x] Кнопка в ProgramView, OlympiadResults/UniversityBenefits, DiplomasView (стили прототипа)
- [x] Тост «Ссылка скопирована», haptic success

## Критерии приёмки
- [x] В браузере ссылка копируется или открывается системное меню
- [ ] В MAX открывается выбор чата — проверено «как из MAX» (Bridge загружен, вызов `shareMaxContent`); в самом MAX — после привязки адреса мини-приложения
- [x] `just check` зелёный

## Контекст
ТЗ: [F-01-share.md](../specs/F-01-share.md). lib/max.ts (shareMaxContent уже типизирован), MaxProvider. До готовности T-011 — мок API.

## Журнал
- 2026-11-07 — Raytist — `shareMaxContent` открывает выбор чата только в ответ на нажатие, поэтому
  `ShareButton` создаёт ссылку заранее (useQuery, POST идемпотентен), а по нажатию сразу
  вызывает меню. Скрытая вкладка «Дипломы» ссылку не создаёт. Ответа меню кнопка не ждёт:
  вне MAX клиент не отвечает, и кнопка зависала. Проверено в браузере 390×844: карточка
  направления, олимпиада → профиль → вуз, итоги дипломов, копирование и тост.
- 2026-11-07 — Raytist — PR #14 сливается в `dev` (squash), CI зелёный.
