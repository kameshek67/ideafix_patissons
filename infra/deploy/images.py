"""Готовит compose-оверрайд с образами из GHCR для деплоя (вызывается в CI).

  python3 infra/deploy/images.py <registry> <tag> <каталог>

Сервисы берутся из `docker compose config` того стека, что сейчас в main, поэтому скрипт
не нужно править при смене сервисов. Каждому сервису со сборкой (`build:`) назначается
образ `<registry>/<сервис>:<tag>`. В каталог пишутся:
  images.json       — образы; уезжает на сервер вместе с релизом;
  build-cache.json  — кэш слоёв в GHCR, нужен только при сборке в CI;
  services          — список собираемых сервисов, по строке.
"""

import json
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
    images, cache = {}, {}
    for name in built:
        repo = f"{registry}/{name}"
        images[name] = {"image": f"{repo}:{tag}"}
        cache[name] = {
            "build": {
                "cache_from": [f"type=registry,ref={repo}:buildcache"],
                "cache_to": [f"type=registry,ref={repo}:buildcache,mode=max,ignore-error=true"],
            }
        }
    out.mkdir(parents=True, exist_ok=True)
    (out / "images.json").write_text(json.dumps({"services": images}, indent=2) + "\n")
    (out / "build-cache.json").write_text(json.dumps({"services": cache}, indent=2) + "\n")
    (out / "services").write_text("\n".join(built) + "\n")
    print(" ".join(built))


if __name__ == "__main__":
    main()
