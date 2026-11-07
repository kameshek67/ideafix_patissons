# Подключить мини-приложение MAX

Как это устроено внутри — [architecture/max-mini-app.md](../architecture/max-mini-app.md).

Нужны бот на платформе MAX для партнёров (https://business.max.ru/self, раздел «Чат-боты»)
и публичный HTTPS-адрес сайта.

1. **Токен бота.** business.max.ru → Чат-боты → ваш бот → ⋮ → Настройки → скопируйте токен.
   В корне проекта создайте `.env` (`cp .env.example .env`, если его ещё нет) и впишите:

   ```dotenv
   OLYMP_MAX_BOT_TOKEN=токен_бота
   OLYMP_MAX_BOT_NAME=имя_бота_без_@
   ```

   По токену API проверяет подпись данных запуска (initData) — так сервер узнаёт пользователя
   MAX. Токен — секрет: он живёт только в `.env`, а этот файл не попадает в git.

2. **HTTPS-адрес.** MAX открывает мини-приложения только по https. Без своего сервера —
   временный адрес Cloudflare (меняется при каждом перезапуске туннеля):

   ```bash
   docker compose --profile tunnel up --build -d
   docker compose logs tunnel | grep trycloudflare.com      # cmd и PowerShell: | findstr trycloudflare.com
   ```

   Если порты 8080/8000 заняты прежним прототипом (контейнеры `bvi-*`), раскомментируйте
   в `.env` строки `OLYMP_WEB_PORT=18080` и `OLYMP_API_PORT=18000` — иначе `api` не стартует
   («port is already allocated»). Туннелю порты не важны: он ходит к сайту внутри сети Docker.
   Если Docker выходит в интернет через VPN-клиент (системный прокси), во время сборки он должен
   быть включён — иначе ошибка `connecting to 127.0.0.1:…: actively refused`. Образы, собранные
   раньше, пересобирать не нужно: `docker compose --profile tunnel up -d` без `--build`.

   На своём сервере с доменом (DNS указывает на сервер, порты 80 и 443 открыты) впишите в `.env`
   `OLYMP_DOMAIN=olymp.example.ru` и запустите `docker compose --profile https up --build -d` —
   Caddy сам получит сертификат Let's Encrypt.

3. **Подключите мини-приложение к боту.** business.max.ru → Чат-боты → бот → ⋮ → Настройки →
   поле ссылки на мини-приложение: вставьте адрес из шага 2, выберите кнопку «Открыть»,
   сохраните. В чате с ботом появится кнопка запуска.

4. **Проверка.** Откройте бота в MAX → «Открыть» → вкладка «Дипломы» → добавьте диплом.
   Под заголовком «Мои дипломы» должно быть «Сохранено в профиле MAX». Если написано
   «Сохранено на этом устройстве», API не видит токен: проверьте `.env`, адрес
   `/api/v1/max/config` на сайте (должно быть `"enabled": true`) и перезапустите API —
   `docker compose up -d api`.

Ссылки, которые открывают мини-приложение сразу на нужном экране (параметр `startapp`):
`https://max.ru/<бот>?startapp=diplomas` — «Мои дипломы», `?startapp=olympiad-<id>` — выдача
по олимпиаде, `?startapp=program-<id>` — карточка направления.

**Приветствие бота (необязательно).** Без него бот ничего не отвечает на кнопку «Начать», хотя
кнопка запуска мини-приложения в чате есть. Профиль `bot` отвечает приветствием с кнопками
«Открыть «Олимп»» и «Мои дипломы»:

```bash
docker compose run --rm bot olymp-max-bot check   # токен рабочий? имя бота и ссылки
docker compose --profile bot up --build -d        # приветствие (long polling)
```

API бота (`platform-api2.max.ru`) подписан сертификатом Минцифры, которого нет в обычных
наборах доверенных: положите корневой сертификат «Russian Trusted Root CA» в `infra/certs`
(инструкция — [infra/certs/README.md](../../infra/certs/README.md)). Самому мини-приложению сертификат не нужен — подпись
данных запуска проверяется локально. Профили можно совмещать:
`docker compose --profile tunnel --profile bot up --build -d`.

**Проверка без телефона.** `scripts/max_dev_link.py` печатает ссылку, которая открывает сайт
в обычном браузере так, будто его запустил MAX: данные запуска подписываются тем же токеном,
что у API (для проверки подойдёт любой, например `local-test-token`).

```bash
OLYMP_MAX_BOT_TOKEN=local-test-token uv run python scripts/max_dev_link.py --start diplomas
```
