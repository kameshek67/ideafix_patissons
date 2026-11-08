# Развёртывание

## Основной стенд — https://ideafix.patissons.tech

**Выкатка автоматическая:** каждый коммит в `main`, на котором прошёл `ci`, собирается в образы
(GHCR) и выкатывается на сервер workflow `.github/workflows/deploy.yml`. Если сайт не ответил за
3 минуты, поднимается предыдущий релиз. Отсюда главное правило: **слияние в `main` = выкатка на
прод**, поэтому в `main` попадают только релизные PR из `dev` и hotfix'ы ([release.md](../guides/release.md)).

Устройство, секреты, работа на сервере, откат, бэкапы — [infra/deploy/README.md](../../infra/deploy/README.md).
Коротко:

| Что | Где / как |
|---|---|
| Секреты стенда (токен бота MAX, `COMPOSE_PROFILES`) | `/opt/ideafix/shared/.env` на сервере |
| Файлы не из git (сертификат Минцифры) | `/opt/ideafix/shared/files/<путь в репозитории>` |
| Логи, статус | `ideafix logs -f --tail 100`, `ideafix ps` |
| Откат | Actions → deploy → старый запуск → Re-run, или `remote.sh <sha> --no-pull` |
| Ручная выкатка последнего `main` | Actions → deploy → Run workflow |
| Дампы PostgreSQL | `/var/backups/ideafix`, ежедневно в 04:30, 14 дней |
| Мониторинг | Telegram-бот Sentry Patissons |

HTTPS даёт Caddy на хосте; профили `https` и `tunnel` из `docker-compose.yml` на стенде не включать.
Порты контейнеров на сервере — только `127.0.0.1`.

### Проверка после выкатки

- [ ] Job `deploy` зелёный (он сам проверяет сайт снаружи по https).
- [ ] Вкладки «Вузы», «Олимпиады», «Дипломы» работают.
- [ ] https://ideafix.patissons.tech/api/v1/max/config → `"enabled": true`.
- [ ] Из MAX: бот → «Открыть» → «Дипломы» → «Сохранено в профиле MAX» (в настройках бота
      указан адрес стенда — [max-setup.md](max-setup.md), шаг 3).
- [ ] Демо-сценарий из [spec.md §8](../product/spec.md) проходит на телефоне.

### Баллы за достижения (ГТО…)

Не требуют пересборки: сервис `migrate` при каждой выкатке запускает `olymp-extra-points` и заменяет
баллы данными из `data/individual_achievements*.csv`. Вручную: `ideafix run --rm migrate olymp-extra-points`
(API не блокируется). После выкатки проверь вкладку «Баллы»: вузов с данными должно быть 7.

### Пересборка базы на стенде

При выкатке `migrate` сам пересобирает базу, если изменились XLSX, кэш ссылок или код разбора
(`olymp-ingest --if-stale`); релизы, где этого не было, базу не трогают. Пересборка API не блокирует
(T-064), и `remote.sh` запускает `migrate` до переключения контейнеров, пока работает прежний
релиз: сайт показывает прежние данные, а новые контейнеры стартуют уже на свежей базе. Простой —
только перезапуск api и web (секунды). Принудительно:

```bash
ideafix run --rm migrate olymp-ingest
```

## Запасной вариант — ноутбук + Cloudflare quick tunnel

Если стенд недоступен на демо:

```bash
docker compose --profile tunnel --profile bot up --build -d
docker compose logs tunnel | grep trycloudflare.com      # Windows: | findstr trycloudflare.com
```

Адрес меняется при каждом перезапуске туннеля — вставь новый в настройки бота
([max-setup.md](max-setup.md), шаг 3). Quick tunnel не поддерживает SSE (потоковые ответы
помощника F-02). Ноутбук не должен засыпать.
