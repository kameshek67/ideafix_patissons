"""Кто прислал запрос — для лимитов (T-065).

На стенде цепочка Caddy → сайт Next → API: API видит адрес контейнера сайта, а не посетителя.
Поэтому адрес берём из X-Forwarded-For, но только если соединение пришло от прокси из
внутренней сети, и только последний элемент: его поставил ближайший прокси, а всё левее мог
дописать сам клиент. Caddy на стенде заменяет присланный клиентом заголовок своим.
"""

import ipaddress

from fastapi import Request

from olymp_api.max_auth import HEADER, InitDataError, validate_init_data

# сети, откуда к API ходят свои прокси (контейнер сайта, Caddy на хосте); is_private не подходит —
# он считает «частными» и диапазоны для документации вроде 198.51.100.0/24
PROXY_NETWORKS = [
    ipaddress.ip_network(n)
    for n in ("127.0.0.0/8", "10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "::1/128", "fc00::/7")
]


def _from_proxy(host: str) -> bool:
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return False
    return any(address in network for network in PROXY_NETWORKS)


def client_ip(request: Request) -> str:
    peer = request.client.host if request.client else "unknown"
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded and _from_proxy(peer):
        last = forwarded.split(",")[-1].strip()
        try:
            return str(ipaddress.ip_address(last))
        except ValueError:
            pass  # мусор в заголовке — считаем по адресу соединения
    return peer


def client_key(request: Request) -> str:
    """Пользователь MAX, если его подпись верна, иначе адрес посетителя."""
    settings = request.app.state.settings
    init_data = request.headers.get(HEADER, "")
    if init_data and settings.max_bot_token:
        try:
            user = validate_init_data(init_data, settings.max_bot_token, settings.max_init_data_ttl)
            return f"max:{user.id}"
        except InitDataError:
            pass
    return f"ip:{client_ip(request)}"
