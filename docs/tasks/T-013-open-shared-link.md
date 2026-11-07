---
id: T-013
title: Открытие ссылок s_<token> и /s/<token>
status: todo
priority: P0
area: web
estimate: S
spec: docs/specs/F-01-share.md
depends: [T-011]
owner: ""
branch: ""
pr: ""
updated: 2026-11-07
---

## Цель
Получатель ссылки попадает на тот же экран в MAX и в браузере.

## Что сделать
- [ ] Маршрут app/s/[token] (noindex) → OlympApp с начальным состоянием
- [ ] Обработка start_param `s_<token>` рядом с существующими program-/olympiad-/diplomas
- [ ] Режим «чужие дипломы — только чтение» в DiplomasView; тост «Ссылка устарела»

## Критерии приёмки
- [ ] Ссылка открывает тот же экран
- [ ] Свои дипломы получателя не меняются
- [ ] Старые startapp работают
- [ ] `just check` зелёный

## Контекст
ТЗ: [F-01-share.md](../specs/F-01-share.md). OlympApp.tsx, блок «запуск по ссылке».

## Журнал
