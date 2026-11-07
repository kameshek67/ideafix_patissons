# Выкатка main на ideafix.patissons.tech

Каждый push в `main` выкатывается на https://ideafix.patissons.tech (сервер `2.26.52.44`).

```
push main ─▶ GitHub Actions: собрать образы всех сервисов с build: ─▶ GHCR
                  │
                  └─ ssh deploy@2.26.52.44 upload <sha>   код релиза → /opt/ideafix/releases/<sha>
                     ssh deploy@2.26.52.44 deploy <sha>   remote.sh: pull → up -d → проверка → current
посетитель ─https─▶ Caddy на сервере ─▶ 127.0.0.1:8080 (сайт стека)
```

- Workflow: `.github/workflows/deploy.yml`. Набор сервисов берётся из `docker-compose.yml` того,
  что лежит в `main` (`images.py`), поэтому смена стека (прототип → новый стек) деплой не ломает.
  Единственное условие: сайт публикуется на порт `8080` хоста (так сейчас и у `frontend` прототипа,
  и у `web` нового стека).
- `remote.sh` ждёт до 3 минут, пока `http://127.0.0.1:8080/` ответит. Не ответил — поднимает
  предыдущий релиз, печатает логи контейнеров, и job падает.
- Порты контейнеров на сервере открыты только на `127.0.0.1` (`"ip": "127.0.0.1"` в
  `/etc/docker/daemon.json`), наружу — только Caddy на 80/443. Docker сам открывает порты в
  обход ufw, поэтому без этой настройки API и Swagger были бы видны из интернета.
- HTTPS — Caddy на хосте, а не Traefik из плана T1.16: на этом сервере Caddy уже обслуживает
  другие сайты, и 80/443 у хоста одни.

## Один раз

1. **DNS:** A-запись `ideafix.patissons.tech → 2.26.52.44`. Без неё Caddy не получит сертификат.
2. **Сервер** (от root, идемпотентно):
   ```bash
   tar -C infra/deploy -cz server | ssh root@2.26.52.44 \
     "d=\$(mktemp -d) && tar -xz -C \$d && DEPLOY_PUBKEY='$(cat ~/.ssh/ideafix_deploy.pub)' \$d/server/setup.sh; rm -rf \$d"
   ```
   Пользователь `deploy` (группа docker) входит только ключом CI, и ключ может вызвать лишь
   `ideafix-gate` (upload/deploy). Ещё ставятся сайт Caddy и ежедневный дамп базы.
3. **Секрет GitHub:** Settings → Secrets and variables → Actions → `DEPLOY_SSH_KEY` — приватный ключ
   из пары, чей `.pub` передан в `setup.sh`. Образы публикуются в GHCR встроенным `GITHUB_TOKEN`,
   отдельный токен не нужен.
4. Желательно: защитить `main` (Settings → Branches), чтобы слияние было только после зелёного `ci`.
   Сам deploy тесты не запускает.

## На сервере

```bash
ideafix ps                    # docker compose текущего релиза
ideafix logs -f --tail 100    # логи
nano /opt/ideafix/shared/.env # секреты и настройки стенда (токен бота MAX, COMPOSE_PROFILES)
ideafix up -d                 # применить .env без новой выкатки
ls -t /opt/ideafix/releases   # последние 5 релизов; /opt/ideafix/current — выкаченный
```

Откат на прошлый релиз (его образы держатся на сервере неделю):

```bash
sudo -u deploy /opt/ideafix/releases/<sha>/infra/deploy/remote.sh <sha> --no-pull
```

Позже — через GitHub: Actions → deploy → старый запуск → Re-run jobs.

Дампы PostgreSQL: `/var/backups/ideafix`, раз в сутки в 04:30, хранятся 14 дней
(`systemctl list-timers ideafix-backup`). Лежат на том же сервере, поэтому их стоит копировать
и в другое место.
