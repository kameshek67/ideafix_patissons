---
id: T-085
title: "Бот MAX: кнопка «Сайт», «ты» и подсказка вместо молчания"
status: done
priority: P1
area: workers
estimate: S
spec: docs/runbooks/max-setup.md
depends: []
owner: 34elo
branch: feat/T-085-bot-site-link
pr: 41
updated: 2026-11-08
---

## Цель
Из чата с ботом можно открыть не только мини-приложение, но и сайт в браузере (удобно с компьютера
и тем, у кого мини-приложение не запускается). Бот не молчит на обычные сообщения.

## Что сделать
- [x] Кнопка-ссылка «Сайт «Олимпа»» (`type: link`) под приветствием; адрес — `OLYMP_SITE_URL`,
  по умолчанию https://ideafix.patissons.tech; адрес сайта и в тексте сообщения
- [x] Приветствие на «ты» (как в интерфейсе после T-063), упоминание ИИ-помощника
- [x] На любое другое личное сообщение — подсказка с теми же кнопками; `/help` — приветствие;
  в группах и ботам — молчание, как раньше
- [x] `olymp-max-bot check` показывает адрес кнопки «Сайт»
- [x] `OLYMP_SITE_URL` в docker-compose, `.env.example`, development.md, max-setup.md

## Критерии приёмки
- [x] `uv run pytest apps/workers/tests/test_max_bot.py` зелёный
- [ ] После выкатки: «Начать» в боте → три кнопки, «Сайт» открывает https://ideafix.patissons.tech
- [x] `just check` зелёный (CI)

## Контекст
`apps/workers/src/olymp_workers/max_bot.py`, тесты на поддельном API MAX. Типы кнопок MAX:
`open_app`, `link`, `callback`, `message` и др.

## Журнал
- 2026-11-08 — 34elo — сделано, на настоящем MAX ещё не проверено (нужен доступ к боту).
