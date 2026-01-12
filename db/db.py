from sqlalchemy         import create_engine
from sqlalchemy.orm     import sessionmaker
from dotenv             import load_dotenv

import os

load_dotenv()

ENGINE = create_engine(
    os.environ.get("DB_CONNECTION"),
    pool_size=5,
    max_overflow=10,
    pool_pre_ping=True
)

SessionLocal = sessionmaker(bind=ENGINE, autoflush=False, autocommit=False, future=True)
