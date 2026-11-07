# 0008. Ветки main + dev, squash, Conventional Commits

- Статус: принято
- Дата: 2026-11-07

## Контекст
Были ветки `main` (прототип), `main-new-stack`, `olymp-rebuild`, `feature/my-diplomas`.
Актуальный код лежал не в `main`, параллельные перестройки расходились. Одновременно
работают четыре человека.

## Решение
- `main` всегда готов к демо. В него попадают только релизные PR `dev → main` (merge commit,
  тег `vX.Y.Z`) и `hotfix/*`.
- `dev` — интеграция. Короткие ветки `feat|fix|docs|chore|refactor|test/T-NNN-…` создаются
  от `dev` и сливаются squash.
- Прямые пуши в `main` и `dev` запрещены защитой веток; обязательны CI и одобрение.
- Коммиты — Conventional Commits на русском.
- Прежние версии сохранены тегами `prototype-v1`, `archive/olymp-rebuild`, `archive/main-new-stack`.

## Альтернативы
- Полный GitFlow с `release/*` — лишний шаг для хакатона.
- Trunk-based (только `main`) — нет буфера между интеграцией и демо-версией.

## Последствия
Демо всегда показываем с `main`. Подробности — [CONTRIBUTING.md](../../CONTRIBUTING.md).

## Когда пересмотреть
Если появится постоянный прод — добавить окружение staging, которое разворачивается из `dev`.
