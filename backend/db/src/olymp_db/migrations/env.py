from alembic import context
from olymp_db import models
from olymp_db.session import make_engine

target_metadata = models.Base.metadata


def _include_object(obj, name, type_, reflected, compare_to):  # type: ignore[no-untyped-def]
    return not (type_ == "table" and name == "alembic_version")


def run() -> None:
    engine = context.config.attributes.get("engine") or make_engine()
    with engine.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            include_object=_include_object,
            compare_type=True,
            compare_server_default=True,
        )
        with context.begin_transaction():
            context.run_migrations()


run()
