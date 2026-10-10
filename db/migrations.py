import os

from alembic            import command
from alembic.config     import Config
from sqlalchemy         import inspect

ALEMBIC_INI = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "alembic.ini")

# Revision matching the schema that Base.metadata.create_all() used to create
# before Alembic was introduced.
BASELINE_REVISION = "0001"


def upgrade_db(engine):
    """Bring the schema up to the latest Alembic migration."""
    config = Config(ALEMBIC_INI)
    config.attributes["skip_logging"] = True

    with engine.begin() as connection:
        config.attributes["connection"] = connection

        tables = inspect(connection).get_table_names()
        if "alembic_version" not in tables and "users" in tables:
            # Database created by create_all() before Alembic: mark it as
            # already at the baseline instead of recreating its tables.
            command.stamp(config, BASELINE_REVISION)

        command.upgrade(config, "head")
