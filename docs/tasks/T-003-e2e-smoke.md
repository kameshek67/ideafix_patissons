---
id: T-003
title: E2E-смоук на Playwright для трёх сценариев
status: todo
priority: P1
area: web
estimate: M
spec: ""
depends: [T-001]
owner: ""
branch: ""
pr: ""
updated: 2026-11-07
---

## Цель
Ловить поломки сквозных сценариев (вуз → олимпиады, олимпиада → вузы, дипломы) до демо, в том числе на мобильной ширине.

## Что сделать
- [ ] Playwright в apps/web (`e2e/`), конфиг с проектами desktop и mobile (390×844)
- [ ] 3 сценария на настоящем API со собранной базой; дипломы — через localStorage
- [ ] Сценарий «как из MAX»: ссылка из scripts/max_dev_link.py открывает «Дипломы»
- [ ] Job `e2e` в CI: PostgreSQL → seed → API → next build/start → тесты; артефакты — трейсы при падении
- [ ] `just e2e`

## Критерии приёмки
- [ ] `just e2e` зелёный локально и в CI
- [ ] Падение сохраняет трейс и скриншот
- [ ] `just check` зелёный

## Контекст
Существующие компонентные тесты: apps/web/src/components/*.test.tsx. docs/guides/testing.md.

## Журнал
