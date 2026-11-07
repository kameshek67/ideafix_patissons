# infra — контейнеры и окружения

| Файл | Что |
|---|---|
| `compose.yaml` | окружение для разработки: PostgreSQL, Redis, RabbitMQ (`just up`); API и сайт запускаются с хоста |
| `Dockerfile.api` | образ Python: API, сборка базы, воркер, бот (не от root, с healthcheck) |
| `Dockerfile.web` | образ Next.js; адрес API зашивается в прокси при сборке |
| `certs/` | корневой сертификат Минцифры для API бота MAX — кладётся локально, в git не хранится ([README](certs/README.md)) |
| `deploy/` | стенд https://ideafix.patissons.tech: выкатка `main`, сервер, откат, бэкапы ([README](deploy/README.md)) |

Весь стек одной командой описан в корневом `docker-compose.yml` (сайт :8080, API :8000, профили
`tunnel`, `https`, `bot`). Развёртывание — [docs/runbooks/deploy.md](../docs/runbooks/deploy.md).
