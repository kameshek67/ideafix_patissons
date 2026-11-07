---
id: T-002
title: Включить защиту веток main и dev на GitHub
status: todo
priority: P0
area: infra
estimate: S
spec: ""
depends: [T-001]
owner: ""
branch: ""
pr: ""
updated: 2026-11-07
---

## Цель
Запретить прямые пуши в main и dev, чтобы все работали только через PR (ADR 0008).

## Что сделать
- [ ] `gh auth login` (делает владелец репозитория)
- [ ] Default branch → dev (PR по умолчанию идут в dev)
- [ ] Защита main и dev: PR обязателен, 1 одобрение, статусы CI `python`, `web`, `secrets`, `tasks` обязательны, запрет force-push и удаления
- [ ] Squash-merge для PR в dev; merge commit — для релизов в main (настройки репозитория)
- [ ] После переезда команды на dev — удалить ветки feature/my-diplomas, main-new-stack, olymp-rebuild (сохранены тегами)

## Критерии приёмки
- [ ] `git push origin dev` без PR отклоняется
- [ ] Новый PR по умолчанию открывается в dev
- [ ] `just check` зелёный

## Контекст
Команды — docs/guides/release.md, раздел «Настройка репозитория».

## Журнал
