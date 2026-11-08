---
id: T-031
title: Колонки confirm_subjects / min_ege_score при сборке
status: done
priority: P0
area: workers
estimate: S
spec: docs/specs/F-03-ege-check.md
depends: [T-030]
owner: 34elo
branch: feat/T-032-ege-api
pr: 68
updated: 2026-11-08
---

## Цель
Числовой порог и коды предметов в базе для быстрых проверок.

## Что сделать
- [x] Миграция 0009 benefits: confirm_subjects text[], min_ege_score smallint
- [x] Заполнение в olymp-ingest (по 213 парам текста, а не по строке), тест ≥ 95% и пример; ege.py — в отпечатке сборки

## Критерии приёмки
- [x] Колонки заполнены, тест сборки зелёный
- [x] `just check` зелёный

## Контекст
ТЗ: [F-03-ege-check.md](../specs/F-03-ege-check.md).

## Журнал
- 2026-11-08 — 34elo — NULL в confirm_subjects — текст не разобран (176 строк), пустой список — предмет по профилю олимпиады. API читает колонки.
