"""Database engine and sessions."""

from sqlalchemy         import create_engine
from sqlalchemy.orm     import sessionmaker

from config             import DB_CONNECTION
from db.migrations      import upgrade_db

engine_kwargs = {"pool_pre_ping": True}
connect_args = {}

if DB_CONNECTION and DB_CONNECTION.startswith("sqlite"):
    # SQLite is file-based; allow access across the bot's worker threads.
    connect_args["check_same_thread"] = False
else:
    # Server databases benefit from a connection pool.
    engine_kwargs["pool_size"] = 5
    engine_kwargs["max_overflow"] = 10

ENGINE = create_engine(DB_CONNECTION, connect_args=connect_args, **engine_kwargs)

SessionLocal = sessionmaker(bind=ENGINE, autoflush=False, autocommit=False, future=True)


def init_db():
    """Apply pending migrations on startup."""
    upgrade_db(ENGINE)
