import os
import tempfile

# Tests always use a throwaway SQLite database, never the one in .env or the
# environment. Must run before anything imports db.db.
_tmpdir = tempfile.mkdtemp(prefix="roman-tech-bot-tests-")
os.environ["DB_CONNECTION"] = f"sqlite:///{os.path.join(_tmpdir, 'test.db')}"

import pytest  # noqa: E402


@pytest.fixture(scope="session")
def db():
    """Database with all migrations applied."""
    from db.db import init_db
    init_db()


@pytest.fixture
def user(db):
    """A fresh user for each test."""
    import random

    from db.repository.user_repository import UserRepository
    return UserRepository().get_or_create(random.randint(10**9, 10**12))
