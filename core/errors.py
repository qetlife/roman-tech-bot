"""Unexpected errors, kept in a file to review now and then ("check the bot's errors").

Every log record at ERROR or above that carries an exception (`logger.exception(…)`,
which is how the bot marks the unexpected cases) goes to `errors.jsonl`, one JSON
object per line, through `ErrorFileHandler`. Expected situations are logged at INFO or
WARNING and stay out. `scripts/errors.py` reads the files and groups them.

- Size: the file rotates at 5 MB and 4 old files are kept (25 MB at most); the
  oldest go first.
- Floods: the same error (its type and the place in the bot's code it came from)
  is written in full at most once an hour. Repeats in between are counted, and
  written as a short line at most every 10 minutes, so a bug in something that
  runs every 20 seconds takes a few KB a day.

No Telegram, no database: it has to work when the database is what's broken.
"""

import json
import logging
import logging.handlers
import threading
import traceback

from dataclasses    import dataclass, field
from datetime       import datetime, timedelta, timezone
from pathlib        import Path
from typing         import Callable, Optional


FILE_NAME = "errors.jsonl"
MAX_BYTES = 5 * 1024 * 1024
BACKUPS = 4
# The full error (with its traceback) at most this often per group…
FULL_EVERY = timedelta(hours=1)
# …and in between, a line counting the repeats at most this often
COUNT_EVERY = timedelta(minutes=10)
# Long messages are cut (a message that crashed the parser could be long)
MESSAGE_LIMIT = 2000

# The bot's own code, to tell where an error came from (not the library it surfaced in)
ROOT = Path(__file__).resolve().parent.parent


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _ours(filename: str) -> bool:
    try:
        path = Path(filename).resolve()
    except (OSError, ValueError):
        return False
    return ROOT in path.parents and "site-packages" not in path.parts and "dist-packages" not in path.parts


def where(exc: BaseException) -> dict:
    """The innermost frame of the error in the bot's own code (else the innermost one): {"file", "function", "line"}."""
    frames = traceback.extract_tb(exc.__traceback__) if exc.__traceback__ else []
    frame = next((f for f in reversed(frames) if _ours(f.filename)), frames[-1] if frames else None)
    if frame is None:
        return {"file": None, "function": None, "line": None}
    filename = Path(frame.filename)
    try:
        filename = filename.resolve().relative_to(ROOT)
    except (OSError, ValueError):
        pass
    return {"file": str(filename), "function": frame.name, "line": frame.lineno}


def group_key(exc: BaseException) -> str:
    """What makes two errors "the same": the exception type and the function it came from (not the line, which moves)."""
    place = where(exc)
    return f"{type(exc).__name__}@{place['file']}:{place['function']}"


class ErrorFile:
    """Writes errors to a rotating file, with the flood protection above. Thread-safe."""

    def __init__(self, directory: str, clock: Callable[[], datetime] = _now, max_bytes: int = MAX_BYTES,
                 backups: int = BACKUPS):
        self.path = Path(directory) / FILE_NAME
        self.clock = clock
        self.lock = threading.Lock()
        # group key → (last full line, last count line, repeats not written yet)
        self.seen = {}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.file = logging.handlers.RotatingFileHandler(self.path, maxBytes=max_bytes, backupCount=backups,
                                                         encoding="utf-8")
        self.file.setFormatter(logging.Formatter("%(message)s"))

    def _write(self, entry: dict) -> None:
        record = logging.LogRecord("errors", logging.ERROR, "", 0, json.dumps(entry, ensure_ascii=False), None, None)
        self.file.emit(record)

    def record(self, exc: BaseException, context: Optional[dict] = None) -> None:
        now = self.clock()
        key = group_key(exc)
        with self.lock:
            last_full, last_count, pending = self.seen.get(key, (None, None, 0))
            pending += 1
            base = {"time": now.isoformat(), "key": key, "count": pending}
            if last_full is None or now - last_full >= FULL_EVERY:
                message = str(exc)
                self._write({
                    **base, "type": type(exc).__name__, "message": message[:MESSAGE_LIMIT], "where": where(exc),
                    "context": context or {},
                    "traceback": "".join(traceback.format_exception(type(exc), exc, exc.__traceback__)),
                })
                self.seen[key] = (now, now, 0)
            elif now - last_count >= COUNT_EVERY:
                self._write(base)
                self.seen[key] = (last_full, now, 0)
            else:
                self.seen[key] = (last_full, last_count, pending)

    def close(self) -> None:
        """Write the repeats not written yet (on shutdown), then close the file."""
        now = self.clock()
        with self.lock:
            for key, (last_full, last_count, pending) in self.seen.items():
                if pending:
                    self._write({"time": now.isoformat(), "key": key, "count": pending})
            self.seen.clear()
        self.file.close()


class ErrorFileHandler(logging.Handler):
    """A logging handler: records with an exception, at ERROR or above, go to an ErrorFile."""

    def __init__(self, errors: ErrorFile):
        super().__init__(level=logging.ERROR)
        self.errors = errors

    def emit(self, record: logging.LogRecord) -> None:
        if not record.exc_info or record.exc_info[1] is None:
            return
        try:
            context = {"logger": record.name, "log": record.getMessage()[:MESSAGE_LIMIT]}
            context.update(getattr(record, "error_context", None) or {})
            self.errors.record(record.exc_info[1], context)
        except Exception:
            # Never let recording an error become another one
            self.handleError(record)


def install(directory: Optional[str]) -> Optional[ErrorFile]:
    """Record unexpected errors under `directory` (the root logger). None (with a warning) if it can't be written."""
    if not directory:
        return None
    try:
        errors = ErrorFile(directory)
    except OSError as e:
        logging.getLogger(__name__).warning("Errors aren't recorded to a file: %s", e)
        return None
    logging.getLogger().addHandler(ErrorFileHandler(errors))
    return errors


# --- reading them back (scripts/errors.py) --------------------------------------

@dataclass
class Group:
    key: str
    count: int = 0
    first: Optional[datetime] = None
    last: Optional[datetime] = None
    # The latest full entry (type, message, where, context, traceback)
    sample: dict = field(default_factory=dict)


def files(directory: str) -> list:
    """errors.jsonl and its rotated copies, oldest first."""
    base = Path(directory) / FILE_NAME
    rotated = sorted(base.parent.glob(FILE_NAME + ".*"), key=lambda p: -int(p.suffix[1:]) if p.suffix[1:].isdigit() else 0)
    return [p for p in rotated + [base] if p.exists()]


def read(directory: str) -> list:
    """Every entry, oldest first. Lines that aren't JSON (a cut-off last line) are skipped."""
    entries = []
    for path in files(directory):
        with open(path, encoding="utf-8", errors="replace") as f:
            for line in f:
                try:
                    entries.append(json.loads(line))
                except ValueError:
                    continue
    return entries


def group(entries: list, since: Optional[datetime] = None) -> list:
    """Entries by group, most frequent first."""
    groups = {}
    for entry in entries:
        when = datetime.fromisoformat(entry["time"])
        if since is not None and when < since:
            continue
        g = groups.setdefault(entry["key"], Group(entry["key"]))
        g.count += entry.get("count", 1)
        g.first = when if g.first is None or when < g.first else g.first
        g.last = when if g.last is None or when > g.last else g.last
        if "traceback" in entry:
            g.sample = entry
    return sorted(groups.values(), key=lambda g: (-g.count, g.key))

