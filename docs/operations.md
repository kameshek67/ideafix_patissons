# Эксплуатация

Для дежурного оператора и того, кто выкатывает релиз. Как устроен код — в
[architecture.md](architecture.md).

## Выкатка

Стенд: https://ideafix.patissons.tech. Выкатывается ветка `main`, вручную ничего делать не нужно.

1. Пуш в `main`, workflow `ci` проходит.
2. Workflow `deploy` (`.github/workflows/deploy.yml`) стартует после зелёного `ci`. Если в `main`
   уже новый коммит, старый не выкатывается.
3. Образы api и web собираются и пушатся в GHCR (`infra/deploy/images.py` готовит compose-оверрайд).
4. Код релиза уходит на сервер по ssh. Ключ CI может вызвать только `ideafix-gate`: `upload` и `deploy`.
5. `infra/deploy/remote.sh` на сервере скачивает образы, запускает миграции и пересборку базы при
   работающем прежнем релизе, поднимает стек и ждёт ответа сайта до трёх минут.
6. Сайт ответил — симлинк `/opt/ideafix/current` переключается на новый релиз; хранятся пять последних.
7. Снаружи проверяются https и то, что порты 8000 и 8080 закрыты.

Нужен один секрет репозитория: `DEPLOY_SSH_KEY`. Секреты стенда лежат в `/opt/ideafix/shared/.env`,
в git их нет. Сервер готовится один раз скриптом `infra/deploy/server/setup.sh`.

### Откат

- Если новый релиз не ответил, `remote.sh` сам поднимает предыдущий, а CI падает с логами контейнеров.
- Откат вручную: Actions → `deploy` → повторный запуск job на нужном коммите. Повторный запуск не
  сверяется с верхушкой `main`.
- Если образы релиза уже на сервере:
  `sudo -u deploy /opt/ideafix/releases/<sha>/infra/deploy/remote.sh <sha> --no-pull`.
- Миграции назад не откатываются. Миграцию, которую нельзя применить поверх старого кода, выкатывай в два шага.

### Команды на сервере

`ideafix ps`, `ideafix logs -f api`, `ideafix exec api sh` — это `docker compose` текущего релиза.

## Переменные окружения

Локально — `.env` (образец — `.env.example`): там значения для разработки и пояснения к каждой
строке. Docker Compose передаёт в контейнеры только перечисленные в `docker-compose.yml`, остальные
читают API, воркеры и тесты напрямую. Полный список настроек API — в
`backend/api/src/olymp_api/settings.py`.

| Группа | Переменные | Что задают |
|---|---|---|
| Общие | `OLYMP_ENV`, `OLYMP_LOG_LEVEL`, `OLYMP_ADMISSION_YEAR`, `OLYMP_DATA_DIR`, `XLSX_PATH`, `SOURCES_CACHE` | окружение (`local`), уровень логов, год поступления, каталог и файлы данных |
| База и кэш | `OLYMP_DATABASE_URL`, `OLYMP_DB_STATEMENT_TIMEOUT_MS`, `OLYMP_DB_LOCK_TIMEOUT_MS`, `OLYMP_REDIS_URL`, `OLYMP_RABBITMQ_URL`, `OLYMP_CACHE_TTL` | адреса, таймауты БД (15000/3000 мс), время жизни кэша (600 с); без Redis всё в памяти процесса |
| Лимиты | `OLYMP_RATE_LIMIT_WINDOW`, `OLYMP_RATE_LIMIT_REQUESTS`, `OLYMP_ASSISTANT_RATE_PER_MINUTE`, `OLYMP_ASSISTANT_RATE_PER_DAY`, `OLYMP_SHARE_RATE_LIMIT`, `OLYMP_SHARE_DAILY_LIMIT`, `OLYMP_REPORT_RATE_LIMIT`, `OLYMP_REPORT_DAILY_LIMIT`, `OLYMP_SHARE_TTL_DAYS` | частоты запросов, сообщений, ссылок и жалоб; 0 снимает ограничение, срок ссылки — дни |
| Помощник | `OLYMP_LLM_ENABLED`, `OLYMP_LLM_BASE_URL`, `OLYMP_LLM_API_KEY`, `OLYMP_LLM_MODEL`, `OLYMP_LLM_FALLBACK_MODEL`, `OLYMP_PARSER_MODEL`, `OLYMP_LLM_TIMEOUT`, `OLYMP_LLM_MAX_TOKENS`, `OLYMP_LLM_TEMPERATURE`, `OLYMP_LLM_TOP_P`, `OLYMP_LLM_DENY_DATA_COLLECTION`, `OLYMP_LLM_DAILY_REQUESTS`, `OLYMP_LLM_PROFILES`, `OLYMP_ASSISTANT_CONTEXT_SECRET` | адрес, ключ и варианты провайдера, таймаут, лимиты, бюджет на сутки; без адреса, ключа и названия помощник выключен |
| MAX | `OLYMP_MAX_BOT_TOKEN`, `OLYMP_MAX_BOT_NAME`, `OLYMP_SITE_URL`, `OLYMP_MAX_OPERATOR_IDS`, `OLYMP_MAX_INIT_DATA_TTL`, `OLYMP_MAX_CA_DIR`, `OLYMP_DOMAIN` | токен и имя бота, кнопка «Сайт», дежурные, срок данных запуска, сертификаты, домен для https |
| Стек и тесты | `OLYMP_API_URL`, `OLYMP_WEB_PORT`, `OLYMP_API_PORT`, `OLYMP_TEST_DATABASE_URL`, `OLYMP_REQUIRE_DB` | адрес API для сайта и бота, порты (8000/8080), база и строгость тестов |

Секреты (`OLYMP_MAX_BOT_TOKEN`, `OLYMP_LLM_API_KEY`, `OLYMP_ASSISTANT_CONTEXT_SECRET` и ключи внутри
`OLYMP_LLM_PROFILES`) в `.env.example` не заданы; настоящие значения — только в `.env` на стенде.

## Бэкап

Раз в сутки таймер `ideafix-backup` на сервере делает `pg_dump` в `/var/backups/ideafix/<база>-<дата>.sql.gz`
и хранит 14 дней (`infra/deploy/server/ideafix-backup`). Копии вне сервера нет, проверка
восстановления не описана — оба пункта в [плане](plan.md).

Восстановление в пустую базу:

```bash
gunzip -c /var/backups/ideafix/olymp-<дата>.sql.gz | ideafix exec -T postgres psql -U olymp -d olymp
```

Данные пользователей (дипломы, жалобы, ссылки «Поделиться») живут только в этой базе. Данные сборки
восстанавливаются заново: `docker compose run --rm migrate olymp-ingest`.

## Жалобы и статусы

Жалоба «не совпадает с документом» приходит от школьника, от сверщика (`olymp-ai-verify`) или
из мониторинга. Причины: льготы нет в документе, другой тип, только для победителей, другой класс или
уровень, другой порог ЕГЭ, ссылка не открывается, другое.

Статусы: `new` → `checking` → `fixed` (исправлено), `correct` (данные верны) или `duplicate`.
`correct` ставится только с цитатой из документа. Статус `seen` остался от выгрузки в CSV.

Как разобрать жалобу:

1. Открой строку и документ вуза по ссылке из жалобы.
2. Ошибки нет — ответь `/quote <№> <цитата из документа>`.
3. Ошибка есть — исправь разбор или справочник в коде и добавь тест. Исходный XLSX не правится.
4. `just data-diff` покажет, как изменилась выдача. Если так и задумано — `just snapshot`.
5. Отметь жалобу `fixed` кнопкой в боте и выгрузи регрессию: `just report-regressions export`.
   Файл `data/regressions/reports.json` коммитится вместе с правкой.
6. Автору из MAX бот отправит ответ сам.

CSV со всеми жалобами: `just reports --all > reports.csv`. Таблица `data_reports` не входит в сборку
базы и переживает её пересборку.

## Бот MAX

Бот (`olymp-max-bot`) здоровается и открывает мини-приложение. Для дежурных из `OLYMP_MAX_OPERATOR_IDS`
он присылает новые жалобы и отвечает на команды:

- `/reports` — открытые жалобы, у каждой кнопки статусов;
- `/quote <№> <текст>` — «данные верны» с цитатой;
- `/stats` — жалобы и «Поделиться» за сутки;
- `/health` — API, база, версия данных, включён ли помощник;
- `/operator` — список команд.

Запуск: `docker compose --profile bot up -d`. API бота подписан сертификатом Минцифры: скачай
«Russian Trusted Root CA» с https://www.gosuslugi.ru/crt и положи `*.pem` или `*.crt` в `infra/certs/`.
Проверить токен: `just max-check`. Открыть сайт «как из MAX» в браузере: `just max-link`.

MAX открывает мини-приложение только по https. Без своего сервера: `docker compose --profile tunnel up -d`
(временный адрес trycloudflare.com). С сервером и доменом: `OLYMP_DOMAIN` в `.env` и `--profile https`.

## Фоновые задачи

RabbitMQ и воркер по умолчанию выключены: задачи запускают вручную, а на сервере с 2 ГБ памяти они
лишние. Включить: `docker compose --profile worker up -d`. Поставить задачу:
`docker compose exec worker python -m olymp_workers.tasks refresh-sources` или `... rebuild`.
Те же действия без очереди: `just refresh-sources`, `just seed`.

Раз в сезон: `just rsosh` (новый перечень РСОШ), `just refresh-sources`, `just data-diff`.

## Разбор новых документов

Оператор даёт ссылку на страницу или документ вуза, сервис сам доводит её до предложения правок,
которое остаётся принять или отклонить. Работает сервис `sources` из `docker-compose.yml`
(`olymp-sources worker`): раз в 10 секунд берёт очередь из таблицы `source_jobs`, RabbitMQ не нужен.

Что делает задача (статусы `queued → fetching → extracting → review → accepted | rejected | failed`):

1. Скачивает ссылку. Страница: ищет на ней документы про олимпиады (PDF, xlsx), списки поступающих
   и приказы о зачислении отбрасывает. Документ: берёт его самого.
2. Извлекает льготы кодом (`olymp-extract`) и проверяет цитаты: запись, цитаты которой нет на
   странице документа, отбрасывается.
3. Сравнивает с текущими строками вуза по ключу (вуз, направление, олимпиада, профиль, тип льготы):
   сколько записей добавится, пропадёт, изменится, плюс до 5 примеров каждого вида с цитатами.
   «Пропадёт» — только то, что эта же ссылка приносила раньше: остальные строки вуза документ
   дополняет и заменяет по ключу, но не удаляет.
4. Если что-то не вышло, в задаче простая причина: «сайт не ответил», «документ — скан без текста»,
   «не нашёл льгот», «на странице нет документов про олимпиады».
5. После «принять» записи ложатся в `document_records` (слой `document` в сборке), а воркер в
   фоне пересобирает базу (`olymp-ingest`, API это не блокирует). Пока пересборка не прошла, у задачи
   `rebuild_needed: true`.

Доступ. В `.env` задай `OLYMP_OPS_TOKEN` (`openssl rand -hex 32`); без него `/v1/ops/*` отвечают 404.
Токен идёт заголовком `Authorization: Bearer …`. Если задан `OLYMP_OPS_WEBHOOK_URL`, воркер шлёт туда
JSON `{job_id, status, university, url, records, error}`, когда задача дошла до `review` или `failed`.

```bash
H="Authorization: Bearer $OLYMP_OPS_TOKEN"; API=https://ideafix.patissons.tech/api/v1/ops
# поставить ссылку на разбор
curl -H "$H" -H 'Content-Type: application/json' $API/sources \
  -d '{"url": "https://pk.mpei.ru/docs/app2_26.pdf", "university": "НИУ «МЭИ»"}'
curl -H "$H" "$API/jobs?status=review"          # что ждёт проверки
curl -H "$H" $API/jobs/12                       # документы, цитаты, разница с базой и примеры
curl -H "$H" -X POST $API/jobs/12/accept        # принять (или .../reject)
curl -H "$H" $API/sources                       # все источники и последняя задача по каждому
```

То же из консоли: `olymp-sources add <url> --university …`, `run <id>` (выполнить здесь и сейчас),
`list`, `accept <id>`, `reject <id>`, `rebuild` (пересобрать базу после приёма без воркера).

Раз в `OLYMP_SOURCES_RECHECK_DAYS` дней (по умолчанию 7) воркер скачивает источник заново: если
sha256 отличается от `last_sha256`, ставит задачу «документ изменился», иначе обновляет `last_checked`.

Ещё не сделано: страница `/ops` на сайте.

Порог, ниже которого вуз разбирается только с ручной проверкой каждой записи: точность записей
не ниже 95%, полнота не ниже 90%, ни одной лишней записи с неверным «кому» или типом льготы.
