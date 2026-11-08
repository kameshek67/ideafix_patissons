---
id: T-032
title: Параметр ege в /v1/achievements/match и хранение баллов в профиле
status: done
priority: P0
area: api
estimate: M
spec: docs/specs/F-03-ege-check.md
depends: [T-031]
owner: 34elo
branch: feat/T-032-ege-api
pr: 68
updated: 2026-11-08
---

## Цель
API считает статус подтверждения льготы баллами ЕГЭ.

## Что сделать
- [x] ege=inf:82 (повторяемый), ege_status/ege_gap/ege_subjects в строках, сводка ege и ege_confirmed у вузов; без ege — как раньше
- [x] Миграция 0008 user_ege_scores, PUT/GET /v1/me/diplomas с ege и ege_is_mock (без поля ege баллы не стираются)
- [x] `just openapi`, тесты

## Критерии приёмки
- [x] Критерии API из F-03
- [x] Старые клиенты без ege получают прежний ответ
- [x] `just check` зелёный

## Контекст
ТЗ: [F-03-ege-check.md](../specs/F-03-ege-check.md).

## Журнал
- 2026-11-08 — 34elo — ответы с баллами не кэшируются (баллы — личные данные, иначе попали бы в ключи Redis). Предмет не указан — по профилю диплома (subject_of_profile).
