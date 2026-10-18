from logging.config import fileConfig
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from alembic import context
from sqlalchemy import engine_from_config, pool

from app.config import get_settings
from app.database.session import Base
from app import models  # noqa: F401 - registers model metadata

config = context.config
if config.config_file_name:
    fileConfig(config.config_file_name)

database_url = get_settings().database_url.replace(
    "postgresql+asyncpg://", "postgresql+psycopg://", 1
)
parsed_url = urlsplit(database_url)
migration_query = [
    ("sslmode" if key == "ssl" else key, value)
    for key, value in parse_qsl(parsed_url.query, keep_blank_values=True)
]
database_url = urlunsplit(
    (
        parsed_url.scheme,
        parsed_url.netloc,
        parsed_url.path,
        urlencode(migration_query),
        parsed_url.fragment,
    )
)
config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(url=database_url, target_metadata=target_metadata, literal_binds=True, compare_type=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        {**config.get_section(config.config_ini_section), "sqlalchemy.url": database_url},
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
