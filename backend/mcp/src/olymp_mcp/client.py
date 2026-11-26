import os
from types import TracebackType
from typing import Any

import httpx

Json = dict[str, Any]
ParamValue = str | int | float | bool | None
Params = list[tuple[str, ParamValue]] | tuple[tuple[str, ParamValue], ...]
DEFAULT_API_URL = "https://ideafix.patissons.tech/api"


class OlympApiError(RuntimeError):
    """Публичный API недоступен или вернул неожиданный ответ."""


class OlympClient:
    def __init__(
        self, base_url: str | None = None, *, transport: httpx.AsyncBaseTransport | None = None
    ) -> None:
        url = base_url or os.environ.get("OLYMP_API_URL") or DEFAULT_API_URL
        self._http = httpx.AsyncClient(
            base_url=url.rstrip("/") + "/", timeout=10.0, transport=transport
        )

    async def __aenter__(self) -> "OlympClient":
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        await self._http.aclose()

    async def get(self, path: str, params: Params = ()) -> Json:
        try:
            response = await self._http.get(path, params=params)
        except httpx.HTTPError as exc:
            raise OlympApiError(f"Олимп API недоступен: {exc.__class__.__name__}") from exc
        if response.is_error:
            raise OlympApiError(f"Олимп API вернул HTTP {response.status_code}")
        try:
            data: Any = response.json()
        except ValueError as exc:
            raise OlympApiError("Олимп API вернул не JSON") from exc
        if not isinstance(data, dict):
            raise OlympApiError("Олимп API вернул не объект")
        return data
