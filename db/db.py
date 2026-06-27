from sqlalchemy         import create_engine
from sqlalchemy.orm     import sessionmaker
from dotenv             import load_dotenv

import os

from models.user        import Base

load_dotenv()

DB_CONNECTION = os.environ.get("DB_CONNECTION")

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
    """Create tables if they don't exist yet."""
    Base.metadata.create_all(ENGINE)
