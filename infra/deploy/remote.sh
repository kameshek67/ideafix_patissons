#!/usr/bin/env bash
# Выкатывает релиз на сервере: скачивает образы из GHCR, поднимает стек, ждёт ответа сайта
# и переключает /opt/ideafix/current. Сайт не ответил — поднимает предыдущий релиз и
# завершается с ошибкой (CI покажет логи контейнеров).
#
# Запускает ideafix-gate по `ssh deploy@… deploy <sha>`; на stdin — логин и токен GHCR.
# Вручную, когда образы уже на сервере (например, откат):
#   sudo -u deploy /opt/ideafix/releases/<sha>/infra/deploy/remote.sh <sha> --no-pull
set -euo pipefail

sha=$1
root=${IDEAFIX_ROOT:-/opt/ideafix}
rel=$root/releases/$sha
health_url=${DEPLOY_HEALTH_URL:-http://127.0.0.1:8080/}
registry=${DEPLOY_REGISTRY:-ghcr.io}
export COMPOSE_PROJECT_NAME=ideafix

log() { echo "[$(date +%T)] $*"; }

compose_in() {  # compose_in <каталог релиза> <аргументы docker compose…>
  local dir=$1 f
  shift
  for f in compose.yaml compose.yml docker-compose.yaml docker-compose.yml; do [ -f "$dir/$f" ] && break; done
  (cd "$dir" && docker compose -f "$f" -f .deploy/images.yml "$@")
}

healthy() {
  for _ in $(seq 1 60); do
    curl -fs -o /dev/null -m 5 "$health_url" && return 0
    sleep 3
  done
  return 1
}

exec 9>"$root/deploy.lock"
flock -w 900 9

# секреты и настройки стенда — один файл на все релизы, в git его нет
ln -sfn "$root/shared/.env" "$rel/.env"
# /usr/local/bin/ideafix из первой версии setup.sh ищет оверрайд под старым именем
ln -sfn images.yml "$rel/.deploy/images.json"
# файлы не из git (сертификат для бота MAX и т. п.): shared/files/<путь> → <релиз>/<путь>
if [ -d "$root/shared/files" ]; then
  cp -a "$root/shared/files/." "$rel/"
fi
# воркер нового стека (uid 10001, infra/Dockerfile.api) пишет в ./data кэш источников
if [ -d "$rel/data" ]; then
  setfacl -R -m u:10001:rwX -m d:u:10001:rwX "$rel/data" 2>/dev/null || chmod -R a+rwX "$rel/data"
fi

if [ "${2:-}" != "--no-pull" ]; then
  read -r user
  read -r token
  # временный конфиг Docker: токен не остаётся на сервере после выкатки
  DOCKER_CONFIG=$(mktemp -d)
  export DOCKER_CONFIG
  trap 'rm -rf "$DOCKER_CONFIG"' EXIT
  printf '%s' "$token" | docker login "$registry" -u "$user" --password-stdin >/dev/null
  mapfile -t services <"$rel/.deploy/services"
  log "скачиваю образы: ${services[*]}"
  compose_in "$rel" pull --quiet "${services[@]}"
  docker logout "$registry" >/dev/null
fi

prev=$(readlink -f "$root/current" 2>/dev/null || true)
log "поднимаю ${sha:0:12}"
if compose_in "$rel" up -d --no-build --remove-orphans && healthy; then
  ln -sfn "$rel" "$root/current.tmp"
  mv -Tf "$root/current.tmp" "$root/current"
  log "готово: $health_url отвечает"
  # пять последних релизов; образы старше недели, которые не использует ни один контейнер
  find "$root/releases" -mindepth 1 -maxdepth 1 -type d -printf '%T@ %p\n' | sort -rn | tail -n +6 \
    | cut -d' ' -f2- | xargs -r rm -rf
  docker image prune -af --filter until=168h >/dev/null || true
  exit 0
fi

log "релиз ${sha:0:12} не поднялся"
compose_in "$rel" ps -a || true
compose_in "$rel" logs --no-color --tail 60 || true
if [ -n "$prev" ] && [ "$prev" != "$rel" ] && [ -d "$prev" ]; then
  log "возвращаю предыдущий релиз $(basename "$prev" | cut -c1-12)"
  if compose_in "$prev" up -d --no-build --remove-orphans && healthy; then
    log "предыдущий релиз отвечает"
  else
    log "предыдущий релиз тоже не отвечает"
  fi
fi
exit 1
