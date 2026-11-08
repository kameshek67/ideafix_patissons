# Сертификаты для API бота MAX

Сайт и мини-приложение этот каталог не используют: подпись данных запуска MAX проверяется
локально, по токену бота, без запросов к MAX.

Он нужен боту (`olymp-max-bot`, профиль `bot` в `docker-compose.yml`) и обходу сайтов вузов
(`olymp-refresh-sources`, `olymp-validate --check-links`, ИИ-карточки): многие сайты вузов подписаны
тем же сертификатом, а TLS проверяется (T-078). В Docker каталог подключён боту и воркеру. Бот ходит в
`https://platform-api2.max.ru`, а этот адрес подписан сертификатом Минцифры («Russian Trusted
Sub CA» → «Russian Trusted Root CA»). В обычных наборах доверенных сертификатов его нет, поэтому
без него бот получит ошибку проверки сертификата.

Что сделать:

1. Скачайте корневой сертификат «Russian Trusted Root CA» с официальной страницы
   https://www.gosuslugi.ru/crt (для Linux-систем — файл в формате `.crt`/`.pem`).
2. Положите файл в этот каталог, например `infra/certs/russian_trusted_root_ca.pem`.
   Подойдут файлы `*.pem`, `*.crt` и `*.cer` (в текстовом PEM-формате).
3. Перезапустите бота: `docker compose --profile bot up -d`.

Запуск бота с хоста (без Docker): `OLYMP_MAX_CA_DIR=infra/certs olymp-max-bot check`.

Файлы сертификатов в git не попадают (см. `.gitignore`).
