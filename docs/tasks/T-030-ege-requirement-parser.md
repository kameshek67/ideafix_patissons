---
id: T-030
title: Разбор порогов ЕГЭ: parse_ege_requirement
status: todo
priority: P0
area: domain
estimate: M
spec: docs/specs/F-03-ege-check.md
depends: [T-073]
owner: ""
branch: ""
pr: ""
updated: 2026-11-07
---

## Цель
Превратить текстовые confirm_subject/min_ege в предметы и число.

## Что сделать
- [ ] Выгрузить уникальные пары значений из собранной базы, посчитать распределение
- [ ] Чистая функция в packages/domain + табличные тесты (≥ 30 реальных случаев)
- [ ] Отчёт о доле разобранных в журнале задачи

## Критерии приёмки
- [ ] ≥ 95% непустых значений разобраны
- [ ] Неразобранные возвращают None без исключений
- [ ] `just check` зелёный

## Контекст
ТЗ: [F-03-ege-check.md](../specs/F-03-ege-check.md). packages/domain/src/olymp_domain/diplomas.py — похожий стиль разбора условий.

## Журнал
