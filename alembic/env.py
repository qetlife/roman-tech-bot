import os

from logging.config import fileConfig

from alembic        import context
from dotenv         import load_dotenv
from sqlalchemy     import create_engine, pool

# Import every model module here so autogenerate sees all tables.
from models.user    import Base

load_dotenv()

config = context.config

# Only configure logging when run from the alembic CLI; when called from the
# bot (db.db.init_db) this would override the bot's own logging setup.
if config.config_file_name is not None and not config.attributes.get("skip_logging"):
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def get_url() -> str:
    url = os.environ.get("DB_CONNECTION")
    if not url:
        raise RuntimeError("DB_CONNECTION is not set")
    return url


def run_migrations_offline() -> None:
    """Emit SQL to stdout instead of running it (alembic upgrade --sql)."""
    url = get_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=url.startswith("sqlite"),
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connection = config.attributes.get("connection")
    if connection is not None:
        # Connection handed over by db.db.init_db
        do_run_migrations(connection)
        return

    engine = create_engine(get_url(), poolclass=pool.NullPool)
    with engine.connect() as connection:
        do_run_migrations(connection)


def do_run_migrations(connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        # SQLite can't ALTER most things; batch mode recreates the table instead.
        render_as_batch=connection.dialect.name == "sqlite",
    )

    with context.begin_transaction():
        context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
