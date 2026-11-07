---
id: T-006
title: Постоянный демо-стенд с HTTPS для MAX
status: done
priority: P0
area: infra
estimate: M
spec: ""
depends: [T-001]
owner: 34elo
branch: t1-16-cicd-deploy
pr: ""
updated: 2026-11-07
---

## Цель
Адрес quick tunnel меняется при каждом перезапуске, и его приходится заново вставлять в настройки бота. Для демо нужен постоянный адрес.

## Что сделать
- [ ] Выбрать: VPS + домен (профиль https, Caddy) или именованный Cloudflare Tunnel
- [ ] Развернуть main, описать в docs/runbooks/deploy.md, включить бота
- [ ] Резервный план: локальный стек + quick tunnel (уже есть)

## Критерии приёмки
- [ ] Мини-приложение открывается из MAX по постоянному адресу (проверить)
- [ ] Обновление — одна команда из runbook
- [ ] `just check` зелёный

## Контекст
docker-compose.yml, профили https и tunnel; docs/runbooks/max-setup.md.

## Журнал
- 2026-11-07 — 34elo — стенд https://ideafix.patissons.tech: автодеплой main после зелёного ci (GHCR + SSH, откат при сбое), Caddy на хосте, порты только на 127.0.0.1, ежедневный дамп БД (коммиты 15dc105, a46b8da; infra/deploy/README.md). Осталось проверить: адрес стенда указан в настройках бота MAX.
