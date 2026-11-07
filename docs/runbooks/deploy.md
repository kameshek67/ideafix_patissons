# Развёртывание демо-стенда

Стенд всегда собирается из `main` (или тега релиза). Постоянный стенд — задача T-006; пока
доступны два способа.

## Вариант 1. Свой сервер с доменом (постоянный адрес)

Требования: Linux-сервер с Docker, домен с A-записью на сервер, открытые порты 80 и 443.

```bash
git clone git@github.com:Raytist/ideafix_patissons.git olymp && cd olymp
git checkout v0.2.0                      # или main
cp .env.example .env                     # впиши OLYMP_DOMAIN, OLYMP_MAX_BOT_TOKEN, OLYMP_MAX_BOT_NAME
docker compose --profile https --profile bot up --build -d
docker compose logs -f migrate           # первая сборка базы ~1 мин
curl -fsS https://$OLYMP_DOMAIN/api/v1/stats | head -c 200
```

Обновление:

```bash
git fetch --tags && git checkout v0.2.1
docker compose --profile https --profile bot up --build -d
```

Пересобрать базу (после изменения сборки или XLSX): `docker compose run --rm migrate olymp-ingest`.
Пользовательские данные (дипломы, ссылки) при этом сохраняются.

## Вариант 2. Ноутбук + Cloudflare quick tunnel (без сервера)

```bash
docker compose --profile tunnel --profile bot up --build -d
docker compose logs tunnel | grep trycloudflare.com      # Windows: | findstr trycloudflare.com
```

Адрес меняется при каждом перезапуске туннеля — вставь новый в настройки бота
([max-setup.md](max-setup.md), шаг 3). Ноутбук не должен засыпать.

## Проверка после развёртывания

- [ ] `https://<адрес>/` открывается, вкладки «Вузы», «Олимпиады», «Дипломы» работают.
- [ ] `https://<адрес>/api/v1/max/config` → `"enabled": true`.
- [ ] Из MAX: бот → «Открыть» → «Дипломы» → «Сохранено в профиле MAX».
- [ ] Демо-сценарий из [spec.md §8](../product/spec.md) проходит на телефоне.

## Откат

```bash
git checkout v<предыдущая>
docker compose --profile https --profile bot up --build -d
```

Миграции только добавляют таблицы и колонки, поэтому откат кода на одну версию назад безопасен.
Миграции с удалением данных требуют отдельного плана отката в PR.
