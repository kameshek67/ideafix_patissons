# Выкатка main на ideafix.patissons.tech

Каждый коммит в `main`, на котором прошёл `ci`, выкатывается на https://ideafix.patissons.tech
(сервер `2.26.52.44`).

```
push main ─▶ ci (тесты) ─зелёный─▶ deploy: собрать образы всех сервисов с build: ─▶ GHCR
                                     │
                                     ├─ ssh deploy@2.26.52.44 upload <sha>   код релиза → /opt/ideafix/releases/<sha>
                                     └─ ssh deploy@2.26.52.44 deploy <sha>   remote.sh: pull → up -d → проверка → current
посетитель ─https─▶ Caddy на сервере ─▶ 127.0.0.1:8080 (сайт стека)
```

- Workflow: `.github/workflows/deploy.yml`. Набор сервисов берётся из `docker-compose.yml` того
  коммита, который выкатывается (`images.py`), поэтому новые сервисы деплой не ломают. Условие одно:
  сайт публикуется на порт `8080` хоста.
- Если `ci` разных коммитов закончился не по порядку, старый коммит поверх нового не выкатывается.
- `remote.sh` ждёт до 3 минут, пока `http://127.0.0.1:8080/` ответит. Не ответил — поднимает
  предыдущий релиз, печатает логи контейнеров, и job падает. Потом job проверяет сайт снаружи по https.
- Порты контейнеров на сервере открыты только на `127.0.0.1` (`"ip": "127.0.0.1"` в
  `/etc/docker/daemon.json`), наружу — только Caddy на 80/443. Docker сам открывает порты в
  обход ufw, поэтому без этой настройки API и Swagger были бы видны из интернета.
- HTTPS — Caddy на хосте, а не Traefik из плана T1.16: на этом сервере Caddy уже обслуживает
  другие сайты, и 80/443 у хоста одни. Профили `https` и `tunnel` из `docker-compose.yml` на стенде
  не включать.
- Доступность сайта, контейнеры и выкатки отслеживает Telegram-бот Sentry Patissons (34elo/SentryPatissonsBot).

## Один раз

1. **DNS:** A-запись `ideafix.patissons.tech → 2.26.52.44`.
2. **Сервер** (от root, идемпотентно):
   ```bash
   tar -C infra/deploy -cz server | ssh root@2.26.52.44 \
     "d=\$(mktemp -d) && tar -xz -C \$d && DEPLOY_PUBKEY='$(cat ~/.ssh/ideafix_deploy.pub)' \$d/server/setup.sh; rm -rf \$d"
   ```
   Пользователь `deploy` (группа docker) входит только ключом CI, и ключ может вызвать лишь
   `ideafix-gate` (upload/deploy). Ещё ставятся сайт Caddy и ежедневный дамп базы.
3. **Секрет GitHub:** Settings → Secrets and variables → Actions → New repository secret,
   имя `DEPLOY_SSH_KEY`, значение — приватный ключ из пары, чей `.pub` передан в `setup.sh`.
   Образы публикуются в GHCR встроенным `GITHUB_TOKEN`, отдельный токен не нужен.

## На сервере

```bash
ideafix ps                    # docker compose текущего релиза
ideafix logs -f --tail 100    # логи
nano /opt/ideafix/shared/.env # секреты и настройки стенда (токен бота MAX, COMPOSE_PROFILES)
ideafix up -d                 # применить .env без новой выкатки
ls -t /opt/ideafix/releases   # последние 5 релизов; /opt/ideafix/current — выкаченный
```

Файлы, которых нет в git (например, сертификат Минцифры для бота MAX), кладутся в
`/opt/ideafix/shared/files/<путь в репозитории>`. При выкатке они копируются в релиз:
`shared/files/infra/certs/russian_trusted_root_ca.pem` → `infra/certs/…`.

Откат на прошлый релиз (его образы держатся на сервере неделю):

```bash
sudo -u deploy /opt/ideafix/releases/<sha>/infra/deploy/remote.sh <sha> --no-pull
```

Или через GitHub: Actions → deploy → нужный старый запуск → Re-run all jobs.

Дампы PostgreSQL: `/var/backups/ideafix`, раз в сутки в 04:30, хранятся 14 дней
(`systemctl list-timers ideafix-backup`). Лежат на том же сервере, поэтому их стоит копировать
и в другое место.
