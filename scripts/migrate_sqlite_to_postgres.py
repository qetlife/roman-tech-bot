"""One-off copy of the bot's data from the legacy SQLite file into PostgreSQL.

Usage:
    python scripts/migrate_sqlite_to_postgres.py <sqlite-url> [<postgres-url>]

    python scripts/migrate_sqlite_to_postgres.py sqlite:////path/to/bot.db "$DB_CONNECTION"

If <postgres-url> is omitted or empty, DB_CONNECTION from the environment is used.

The target schema is created with the Alembic migrations, every row of every model table
is copied with its primary key, and integer id sequences are moved past the
copied ids. A table that already has rows in the target is left untouched and
the script exits with an error, so re-running it never duplicates data.
"""

import os
import sys

from sqlalchemy     import create_engine, func, inspect, make_url, select, text

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from db.migrations  import upgrade_db  # noqa: E402
from db.models.user import Base  # noqa: E402

BATCH_SIZE = 1000


def count_rows(conn, table) -> int:
    return conn.scalar(select(func.count()).select_from(table))


def reset_sequences(conn, table):
    """Point each serial/identity sequence of `table` at max(column)."""
    for column in table.columns:
        seq = conn.scalar(
            text("SELECT pg_get_serial_sequence(:table, :column)"),
            {"table": table.name, "column": column.name},
        )
        if seq is None:
            continue

        conn.execute(
            text(
                f'SELECT setval(:seq, COALESCE((SELECT MAX("{column.name}") FROM "{table.name}"), 0) + 1, false)'
            ),
            {"seq": seq},
        )
        print(f"  reset sequence {seq}")


def main(argv) -> int:
    if len(argv) not in (2, 3):
        print(__doc__)
        return 2

    sqlite_url = argv[1]
    # An empty argument also falls back to the environment: on the host,
    # "$DB_CONNECTION" usually expands to "" because .env is not exported.
    postgres_url = (argv[2] if len(argv) == 3 else "") or os.environ.get("DB_CONNECTION")

    if not sqlite_url.startswith("sqlite"):
        print(f"Source must be a sqlite:// URL, got: {sqlite_url}")
        return 2
    if not postgres_url or not postgres_url.startswith("postgresql+psycopg://"):
        print("Target must be a postgresql+psycopg:// URL (argument or DB_CONNECTION).")
        return 2

    sqlite_path = make_url(sqlite_url).database
    if not sqlite_path or not os.path.isfile(sqlite_path):
        print(f"SQLite file not found: {sqlite_path}")
        return 1

    source = create_engine(sqlite_url)
    target = create_engine(postgres_url)

    source_tables = set(inspect(source).get_table_names())
    if not source_tables:
        print(f"Source database {sqlite_url} has no tables (wrong path?). Nothing to do.")
        return 1

    # Same schema setup the bot runs on startup (Alembic migrations).
    upgrade_db(target)

    tables = Base.metadata.sorted_tables

    # Refuse to touch anything if a target table already has data.
    with target.connect() as conn:
        non_empty = [t.name for t in tables if count_rows(conn, t) > 0]
    if non_empty:
        print(
            "Target already contains rows in: " + ", ".join(non_empty) + ".\n"
            "Nothing was copied. The migration has probably run already; if not, "
            "empty these tables first and re-run."
        )
        return 1

    # One transaction: either every table is copied or nothing is.
    with source.connect() as src, target.begin() as dst:
        for table in tables:
            if table.name not in source_tables:
                print(f"{table.name}: not in source, skipped")
                continue

            print(f"{table.name}: copying...")
            total = 0
            result = src.execute(select(table)).mappings()
            while batch := result.fetchmany(BATCH_SIZE):
                dst.execute(table.insert(), [dict(row) for row in batch])
                total += len(batch)

            reset_sequences(dst, table)

    ok = True
    print("\nRow counts (source -> target):")
    with source.connect() as src, target.connect() as dst:
        for table in tables:
            src_count = count_rows(src, table) if table.name in source_tables else 0
            dst_count = count_rows(dst, table)
            status = "OK" if src_count == dst_count else "MISMATCH"
            ok = ok and src_count == dst_count
            print(f"  {table.name}: {src_count} -> {dst_count} {status}")

    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
