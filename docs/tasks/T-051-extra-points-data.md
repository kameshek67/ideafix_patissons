---
id: T-051
title: Собрать таблицу ИД вузов в data/individual_achievements.csv
status: todo
priority: P3
area: data
estimate: M
spec: docs/specs/F-05-extra-points.md
depends: [T-050]
owner: ""
branch: ""
pr: ""
updated: 2026-11-07
---

## Цель
Без данных о баллах за достижения фичу не сделать: в XLSX их нет (кроме «УрФУ +4 балла»).

## Что сделать
- [ ] Формат CSV: вуз, достижение (код из справочника), баллы, условия, источник (URL + страница)
- [ ] Справочник видов ИД: medal, gto_gold, essay, volunteer, olympiad_non_bvi, creative, sport и др.
- [ ] Заполнить по вузам, выбранным в T-050 (минимум 5, цель — топ-10 из базы)

## Критерии приёмки
- [ ] У каждой строки есть ссылка на документ вуза
- [ ] Справочник видов ИД описан в docs/architecture/data.md
- [ ] `just check` зелёный

## Контекст
ТЗ: [F-05-extra-points.md](../specs/F-05-extra-points.md). Приоритет P3 — сроки решает команда (см. docs/specs/BACKLOG.md).

## Журнал
