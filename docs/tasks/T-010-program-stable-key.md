---
id: T-010
title: Стабильный ключ направления при сборке базы
status: done
priority: P0
area: workers
estimate: S
spec: docs/specs/F-01-share.md
depends: [T-073]
owner: Raytist
branch: feat/T-012-share
pr: 14
updated: 2026-11-07
---

## Цель
Ссылки «Поделиться» на направление должны переживать пересборку базы (ADR 0007).

## Что сделать
- [x] Функция `program_stable_key(university_name, name, profile, code)` в packages/domain + тесты
- [x] ~~Миграция `programs.stable_key`~~ — не нужна: ключ считается на лету из полей направления (см. журнал)
- [x] Тест: ключи уникальны на настоящей сборке и совпадают между двумя сборками

## Критерии приёмки
- [x] Две сборки подряд дают одинаковые ключи
- [x] Ключи уникальны на настоящих данных
- [x] `just check` зелёный

## Контекст
ТЗ: [F-01-share.md](../specs/F-01-share.md). apps/workers/src/olymp_workers/ingest.py (ProgramRegistry), packages/db/models.py.

## Журнал
- 2026-11-07 — Raytist — ключ «вуз|направление|профиль|коды» (squash полного названия вуза, а не
  `short_name`; профиль программы — по ревью). Колонку `programs.stable_key` не завели: деплой
  запускает `olymp-ingest --if-empty` и прод-базу не пересобирает — колонку было бы нечем
  заполнить, а ключ из полей направления сам переживает пересборку. На настоящей сборке
  659 направлений и 39 вузов — совпадений нет (тест в apps/api/tests/test_sharing.py).
- 2026-11-07 — Raytist — PR #14 сливается в `dev` (squash), CI зелёный.
