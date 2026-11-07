"""Готовит compose-оверрайд с образами из GHCR для деплоя (вызывается в CI).

  python3 infra/deploy/images.py <registry> <tag> <каталог>

Сервисы берутся из `docker compose config` того стека, что сейчас в main, поэтому скрипт
не нужно править при смене сервисов. Каждому сервису со сборкой (`build:`) назначается
образ `<registry>/<сервис>:<tag>`. В каталог пишутся:
  images.yml  — образы и сети стека с портами только на 127.0.0.1; уезжает на сервер
                 вместе с релизом;
  build.yml   — кэш слоёв в GHCR и метка org.opencontainers.image.source (по ней GHCR
                 привязывает пакет к репозиторию и даёт его GITHUB_TOKEN право читать), только для CI;
  services     — собираемые сервисы, по строке;
  images       — их образы, по строке (CI проверяет, что все опубликованы).
"""

import json
import os
import subprocess
import sys
from pathlib import Path


def main() -> None:
    registry, tag, out = sys.argv[1], sys.argv[2], Path(sys.argv[3])
    # все профили: образ нужен и сервисам, которые на сервере включают через COMPOSE_PROFILES
    cfg = json.loads(
        subprocess.check_output(
            ["docker", "compose", "--profile", "*", "config", "--format", "json"]
        )
    )
    built = sorted(name for name, svc in cfg["services"].items() if "build" in svc)
    if not built:
        sys.exit("в compose нет сервисов со сборкой — деплоить нечего")
    server = os.environ.get("GITHUB_SERVER_URL", "https://github.com")
    source = (
        f"{server}/{os.environ['GITHUB_REPOSITORY']}" if "GITHUB_REPOSITORY" in os.environ else ""
    )
    # Порты без адреса Docker публикует на 0.0.0.0, в обход ufw: "ip" в daemon.json действует
    # только на docker0, а не на сети compose. Снаружи сайт доступен только через Caddy.
    networks = {
        name: {"driver_opts": {"com.docker.network.bridge.host_binding_ipv4": "127.0.0.1"}}
        for name, net in (cfg.get("networks") or {"default": {}}).items()
        if not net.get("external") and net.get("driver", "bridge") == "bridge"
    }
    images, build = {}, {}
    for name in built:
        repo = f"{registry}/{name}"
        images[name] = {"image": f"{repo}:{tag}"}
        build[name] = {
            "build": {
                "cache_from": [f"type=registry,ref={repo}:buildcache"],
                "cache_to": [f"type=registry,ref={repo}:buildcache,mode=max,ignore-error=true"],
                "labels": {"org.opencontainers.image.source": source} if source else {},
            }
        }
    out.mkdir(parents=True, exist_ok=True)
    deploy = {"services": images, "networks": networks}
    (out / "images.yml").write_text(json.dumps(deploy, indent=2) + "\n")
    (out / "build.yml").write_text(json.dumps({"services": build}, indent=2) + "\n")
    (out / "services").write_text("\n".join(built) + "\n")
    (out / "images").write_text("\n".join(images[n]["image"] for n in built) + "\n")
    print(" ".join(built))


if __name__ == "__main__":
    main()
