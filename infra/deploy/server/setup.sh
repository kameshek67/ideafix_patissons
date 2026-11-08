#!/usr/bin/env bash
# Подготовка сервера к выкатке из CI. Идемпотентна, запускать от root на сервере:
#   tar -C infra/deploy -cz server | ssh root@2.26.52.44 \
#     "d=\$(mktemp -d) && tar -xz -C \$d && DEPLOY_PUBKEY='$(cat ~/.ssh/ideafix_deploy.pub)' \$d/server/setup.sh; rm -rf \$d"
#
# Что делает: Docker (порты контейнеров только на 127.0.0.1), пользователь deploy с ключом CI,
# который может лишь вызвать ideafix-gate, каталоги /opt/ideafix, сайт в Caddy, дамп базы раз в сутки.
set -euo pipefail
here=$(cd "$(dirname "$0")" && pwd)
root=/opt/ideafix

# ---- Docker: опубликованные порты — только на loopback, наружу ходят через Caddy.
# Иначе Docker открывает порты в обход ufw.
if ! command -v docker >/dev/null; then
  install -d /etc/docker
  [ -f /etc/docker/daemon.json ] || cat >/etc/docker/daemon.json <<'EOF'
{
  "ip": "127.0.0.1",
  "log-driver": "local",
  "log-opts": {"max-size": "20m", "max-file": "5"},
  "live-restore": true
}
EOF
  install -m 0755 -d /etc/apt/keyrings
  curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
  chmod a+r /etc/apt/keyrings/docker.asc
  . /etc/os-release
  cat >/etc/apt/sources.list.d/docker.sources <<EOF
Types: deb
URIs: https://download.docker.com/linux/ubuntu
Suites: $VERSION_CODENAME
Components: stable
Signed-By: /etc/apt/keyrings/docker.asc
EOF
  apt-get update -qq
  DEBIAN_FRONTEND=noninteractive apt-get install -y -qq docker-ce docker-ce-cli containerd.io \
    docker-buildx-plugin docker-compose-plugin
fi
command -v setfacl >/dev/null || DEBIAN_FRONTEND=noninteractive apt-get install -y -qq acl
# "ip" действует только на docker0; сетям compose тот же адрес по умолчанию даёт
# default-network-opts (деплой ещё и сам задаёт его сети стека — images.py)
python3 - <<'PY' && systemctl restart docker
import json, sys
from pathlib import Path
p = Path("/etc/docker/daemon.json")
d = json.loads(p.read_text()) if p.exists() else {}
want = {"bridge": {"com.docker.network.bridge.host_binding_ipv4": "127.0.0.1"}}
if d.get("ip") == "127.0.0.1" and d.get("default-network-opts") == want:
    sys.exit(1)  # уже так — docker не перезапускаем
d.update({"ip": "127.0.0.1", "default-network-opts": want})
p.write_text(json.dumps(d, indent=2) + "\n")
PY

# ---- пользователь deploy: группа docker, вход только ключом CI и только в ideafix-gate
id deploy >/dev/null 2>&1 || useradd --system --create-home --home-dir /home/deploy --shell /bin/bash deploy
usermod -aG docker deploy
passwd -l deploy >/dev/null
install -m 755 "$here/ideafix-gate" /usr/local/bin/ideafix-gate
install -m 755 "$here/ideafix" /usr/local/bin/ideafix
if [ -n "${DEPLOY_PUBKEY:-}" ]; then
  install -d -m 700 -o deploy -g deploy /home/deploy/.ssh
  opts='command="/usr/local/bin/ideafix-gate",no-port-forwarding,no-X11-forwarding,no-agent-forwarding,no-pty'
  echo "$opts $DEPLOY_PUBKEY" >/home/deploy/.ssh/authorized_keys
  chown deploy:deploy /home/deploy/.ssh/authorized_keys
  chmod 600 /home/deploy/.ssh/authorized_keys
fi

# ---- каталоги: релизы пишет deploy, .env (секреты стенда) читает deploy, правит root
install -d -m 755 -o deploy -g deploy "$root" "$root/releases"
install -d -m 750 -o root -g deploy "$root/shared"
install -d -m 750 -o root -g deploy "$root/shared/files"
if [ ! -f "$root/shared/.env" ]; then
  cat >"$root/shared/.env" <<'EOF'
# Настройки и секреты стенда ideafix.patissons.tech. Не в git; docker compose читает файл
# при каждой выкатке. После правки: ideafix up -d (или дождаться следующей выкатки).
#
# Мини-приложение MAX: токен и имя бота (business.max.ru → Чат-боты)
# OLYMP_MAX_BOT_TOKEN=
# OLYMP_MAX_BOT_NAME=
# Бот с кнопкой «Открыть» — ещё и сертификат Минцифры в
# /opt/ideafix/shared/files/infra/certs/ (см. README, раздел «Мини-приложение MAX»):
# COMPOSE_PROFILES=bot
# Профили https и tunnel на стенде не включать: HTTPS даёт Caddy сервера.
EOF
  chown root:deploy "$root/shared/.env"
  chmod 640 "$root/shared/.env"
fi

# ---- Caddy: по файлу на сайт в /etc/caddy/sites
if command -v caddy >/dev/null; then
  install -d /etc/caddy/sites
  install -m 644 "$here/ideafix.caddy" /etc/caddy/sites/ideafix.caddy
  grep -q '^import /etc/caddy/sites/\*.caddy' /etc/caddy/Caddyfile 2>/dev/null \
    || echo 'import /etc/caddy/sites/*.caddy' >>/etc/caddy/Caddyfile
  caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile >/dev/null
  systemctl enable caddy >/dev/null 2>&1
  systemctl reload-or-restart caddy
else
  echo "ВНИМАНИЕ: Caddy не установлен — HTTPS не настроен" >&2
fi

# ---- дамп базы раз в сутки
install -m 755 "$here/ideafix-backup" /usr/local/bin/ideafix-backup
cat >/etc/systemd/system/ideafix-backup.service <<'EOF'
[Unit]
Description=Дамп PostgreSQL стенда ideafix
After=docker.service

[Service]
Type=oneshot
ExecStart=/usr/local/bin/ideafix-backup
EOF
cat >/etc/systemd/system/ideafix-backup.timer <<'EOF'
[Unit]
Description=Ежедневный дамп PostgreSQL стенда ideafix

[Timer]
OnCalendar=*-*-* 04:30
Persistent=true

[Install]
WantedBy=timers.target
EOF
systemctl daemon-reload
systemctl enable --now ideafix-backup.timer >/dev/null 2>&1

echo "сервер готов: deploy $(id -nG deploy), caddy $(systemctl is-active caddy 2>/dev/null || echo нет)"
