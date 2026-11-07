---
id: T-033
title: Блок «Мои баллы ЕГЭ» и статусы в «Дипломах»
status: todo
priority: P0
area: web
estimate: M
spec: docs/specs/F-03-ege-check.md
depends: [T-032]
owner: ""
branch: ""
pr: ""
updated: 2026-11-07
---

## Цель
Школьник видит «подтверждено» или «не хватает N баллов».

## Что сделать
- [ ] Блок ввода баллов (0–100, «пробные»), хранение в useMyDiplomas
- [ ] Колонка «ЕГЭ» с чипами статусов, строка в итогах, фильтр «Только подтверждённые»
- [ ] Тесты компонента

## Критерии приёмки
- [ ] Критерии интерфейса из F-03
- [ ] `just check` зелёный

## Контекст
ТЗ: [F-03-ege-check.md](../specs/F-03-ege-check.md). DiplomasView.tsx, DiplomaSheet.tsx, useMyDiplomas.ts.

## Журнал
