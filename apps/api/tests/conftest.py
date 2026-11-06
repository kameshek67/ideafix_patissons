from collections.abc import AsyncIterator

import httpx
import pytest
from olymp_api.main import create_app
from olymp_api.settings import Settings


@pytest.fixture
async def client(built_database_url: str) -> AsyncIterator[httpx.AsyncClient]:
    app = create_app(Settings(database_url=built_database_url, rate_limit_requests=0))
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    await app.state.engine.dispose()
