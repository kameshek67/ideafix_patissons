# 0003. Стек и монорепозиторий

- Статус: принято
- Дата: 2026-11-07

## Контекст
Прототип (тег `prototype-v1`) — SQLite и чистый JS в одном файле. Его сложно развивать:
нужны аккаунты, параллельная запись, мини-приложение, тесты компонентов.

## Решение
- Python 3.13 + uv workspace: `packages/{domain,db}`, `apps/{api,workers}`.
- FastAPI, SQLAlchemy 2 + Alembic, PostgreSQL 17, Redis (необязателен), Dramatiq + RabbitMQ.
- Next.js 16 + React 19 + TanStack Query, npm workspaces: `apps/web`, `packages/api-client`.
- Docker Compose для всего стека, `just` для команд, GitHub Actions для CI.

Таблица с назначением каждой технологии — [stack.md](../architecture/stack.md).

## Альтернативы
- Один язык (TypeScript) на всё — но разбор XLSX и PDF и нормализация текста уже написаны на Python.
- Django — тяжелее, а его ORM и админка в таком виде не нужны.

## Последствия
Два менеджера пакетов (uv и npm) и два набора линтеров; `just check` объединяет их.

## Когда пересмотреть
Не раньше окончания хакатона.
