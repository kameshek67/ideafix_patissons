"""`python -m olymp_api.openapi_cli` печатает OpenAPI-контракт (docs/openapi.json)."""

import json

from .main import create_app
from .settings import Settings


def main() -> None:
    app = create_app(Settings(database_url=None))
    print(json.dumps(app.openapi(), ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
