---
id: T-051
title: Собрать таблицу ИД вузов в data/individual_achievements.csv
status: review
priority: P3
area: data
estimate: M
spec: docs/specs/F-05-extra-points.md
depends: [T-050]
owner: 34elo
branch: feat/T-050-054-extra-points-v2
pr: 17
updated: 2026-11-07
---

## Цель
Без данных о баллах за достижения фичу не сделать: в XLSX их нет (кроме «УрФУ +4 балла»).

## Что сделать
- [x] Формат CSV: вуз, достижение (код из справочника), баллы, условия, источник (URL + страница)
- [x] Справочник видов ИД: medal, gto_gold, essay, volunteer, olympiad_non_bvi, creative, sport и др.
- [x] Заполнить по вузам, выбранным в T-050 (минимум 5, цель — топ-10 из базы)

## Критерии приёмки
- [x] У каждой строки есть ссылка на документ вуза
- [x] Справочник видов ИД описан в docs/architecture/data.md
- [ ] `just check` зелёный

## Контекст
ТЗ: [F-05-extra-points.md](../specs/F-05-extra-points.md). Приоритет P3 — сроки решает команда (см. docs/specs/BACKLOG.md).

## Журнал

- 2026-11-07: два CSV (правила и лимиты). Виды вместо `gto_gold` — тип `gto_badge` + степень в `variants` (баллы за степень у вузов разные). Справочник видов: `KINDS` в `olymp_domain.extra_points`, описание в F-05. 223 правила, 6 лимитов, все `review=extracted`: баллы человек ещё не сверял.
