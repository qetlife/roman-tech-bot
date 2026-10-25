import asyncio
import json
import logging

from datetime       import datetime, timedelta, timezone
from unittest.mock  import AsyncMock, MagicMock

import pytest

from telegram       import Update
from telegram.error import Forbidden, NetworkError

from core           import errors
from core.errors    import ErrorFile, ErrorFileHandler, group, group_key, read, where
from handlers       import errors as error_handler
from scripts        import errors as script


START = datetime(2026, 10, 25, 12, 0, tzinfo=timezone.utc)


class Clock:
    def __init__(self):
        self.now = START

    def __call__(self):
        return self.now


def _boom(message="boom"):
    raise ValueError(message)


def _caught(message="boom") -> BaseException:
    try:
        _boom(message)
    except ValueError as e:
        return e


def _lines(directory) -> list:
    return [json.loads(line) for line in (directory / errors.FILE_NAME).read_text().splitlines()]


def test_where_and_group_key_point_at_the_bots_code():
    e = _caught()
    assert where(e)["file"] == "tests/test_errors.py"
    assert where(e)["function"] == "_boom"
    assert group_key(e) == "ValueError@tests/test_errors.py:_boom"
    # Not raised: no traceback, no place
    assert where(ValueError("x")) == {"file": None, "function": None, "line": None}


def test_the_same_error_is_written_in_full_once_an_hour_and_counted_in_between(tmp_path):
    clock = Clock()
    f = ErrorFile(str(tmp_path), clock=clock)
    f.record(_caught("first"), {"user": 1})
    for minutes in (1, 2, 3):
        clock.now = START + timedelta(minutes=minutes)
        f.record(_caught())
    lines = _lines(tmp_path)
    assert len(lines) == 1
    assert lines[0]["message"] == "first" and lines[0]["context"] == {"user": 1} and "traceback" in lines[0]

    # 10 minutes after the last line: the repeats so far as one count line
    clock.now = START + timedelta(minutes=10)
    f.record(_caught())
    lines = _lines(tmp_path)
    assert lines[1] == {"time": clock.now.isoformat(), "key": lines[0]["key"], "count": 4}

    # An hour after the full one: in full again
    clock.now = START + timedelta(hours=1)
    f.record(_caught("again"))
    assert _lines(tmp_path)[2]["message"] == "again"

    # A different error isn't held back by this one
    try:
        {}["missing"]
    except KeyError as e:
        f.record(e)
    assert _lines(tmp_path)[3]["type"] == "KeyError"
    f.close()


def test_close_writes_the_repeats_not_written_yet(tmp_path):
    clock = Clock()
    f = ErrorFile(str(tmp_path), clock=clock)
    for _ in range(3):
        f.record(_caught())
    f.close()
    lines = _lines(tmp_path)
    assert len(lines) == 2 and lines[1]["count"] == 2
    assert group(read(str(tmp_path)))[0].count == 3


def test_the_file_rotates_and_keeps_a_few_old_ones(tmp_path):
    clock = Clock()
    f = ErrorFile(str(tmp_path), clock=clock, max_bytes=2000, backups=2)
    for hour in range(20):
        clock.now = START + timedelta(hours=hour)
        f.record(_caught("x" * 500))
    f.close()
    names = sorted(p.name for p in tmp_path.iterdir())
    assert names == ["errors.jsonl", "errors.jsonl.1", "errors.jsonl.2"]
    assert all(p.stat().st_size <= 2000 + 2000 for p in tmp_path.iterdir())
    entries = read(str(tmp_path))
    # Oldest first, the newest kept
    times = [e["time"] for e in entries]
    assert times == sorted(times) and times[-1] == (START + timedelta(hours=19)).isoformat()


def test_read_skips_a_cut_off_line_and_group_counts_by_kind(tmp_path):
    lines = [
        {"time": START.isoformat(), "key": "A", "count": 1, "type": "ValueError", "message": "a", "traceback": "…"},
        {"time": (START + timedelta(minutes=10)).isoformat(), "key": "A", "count": 5},
        {"time": (START + timedelta(days=2)).isoformat(), "key": "B", "count": 1, "message": "b", "traceback": "…"},
    ]
    (tmp_path / errors.FILE_NAME).write_text("\n".join(json.dumps(l) for l in lines) + '\n{"time": "cut')
    groups = group(read(str(tmp_path)))
    assert [(g.key, g.count) for g in groups] == [("A", 6), ("B", 1)]
    assert groups[0].first == START and groups[0].last == START + timedelta(minutes=10)
    assert groups[0].sample["message"] == "a"
    assert [g.key for g in group(read(str(tmp_path)), since=START + timedelta(days=1))] == ["B"]
    assert read(str(tmp_path / "nothing")) == []


def test_install_without_a_writable_directory_doesnt_crash(tmp_path):
    blocker = tmp_path / "file"
    blocker.write_text("")
    assert errors.install(str(blocker / "errors")) is None
    assert errors.install("") is None


def test_the_handler_takes_only_errors_with_an_exception(tmp_path):
    f = ErrorFile(str(tmp_path), clock=Clock())
    log = logging.getLogger("test_errors")
    handler = ErrorFileHandler(f)
    log.addHandler(handler)
    try:
        log.error("no exception")
        try:
            _boom()
        except ValueError:
            log.warning("expected", exc_info=True)
            log.exception("Sending %s failed", "a reminder", extra={"error_context": {"reminder": 7}})
    finally:
        log.removeHandler(handler)
        f.close()
    [line] = _lines(tmp_path)
    assert line["context"] == {"logger": "test_errors", "log": "Sending a reminder failed", "reminder": 7}


def _update(**kwargs):
    update = MagicMock(spec=Update)
    update.effective_user = MagicMock(id=42)
    update.callback_query = kwargs.get("callback_query")
    update.effective_message = kwargs.get("message")
    return update


def _message(text=None, voice=None):
    message = MagicMock(text=text, voice=voice)
    message.reply_text = AsyncMock()
    return message


def test_describe_never_holds_the_users_text():
    secret = "remind me to pick up my prescription"
    assert error_handler.describe(_update(message=_message(secret))) == {"user": 42, "update": "message"}
    assert error_handler.describe(_update(message=_message("/start abc"))) == \
        {"user": 42, "update": "command", "command": "/start"}
    assert error_handler.describe(_update(message=_message(voice=object()))) == \
        {"user": 42, "update": "voice message"}
    query = MagicMock(data="menu:main")
    assert error_handler.describe(_update(callback_query=query)) == \
        {"user": 42, "update": "button", "data": "menu:main"}
    assert error_handler.describe(None) == {"update": None}


def _on_error(update, error, caplog):
    context = MagicMock(error=error)
    with caplog.at_level(logging.WARNING, logger="handlers.errors"):
        asyncio.run(error_handler.on_error(update, context))


def test_on_error_records_and_says_sorry(caplog):
    message = _message("something private")
    _on_error(_update(message=message), _caught(), caplog)
    [record] = [r for r in caplog.records if r.name == "handlers.errors"]
    assert record.levelno == logging.ERROR and record.exc_info[0] is ValueError
    assert record.error_context == {"user": 42, "update": "message"}
    message.reply_text.assert_awaited_once_with(error_handler.SORRY)

    query = MagicMock(data="x")
    query.answer = AsyncMock()
    _on_error(_update(callback_query=query), _caught(), caplog)
    query.answer.assert_awaited_once_with(error_handler.SORRY, show_alert=True)


@pytest.mark.parametrize("error", [NetworkError("timed out"), Forbidden("bot was blocked by the user")])
def test_telegram_hiccups_are_only_warnings(error, caplog):
    message = _message("hi")
    _on_error(_update(message=message), error, caplog)
    assert [r.levelno for r in caplog.records if r.name == "handlers.errors"] == [logging.WARNING]
    message.reply_text.assert_not_awaited()


def test_script(tmp_path, capsys):
    clock = Clock()
    f = ErrorFile(str(tmp_path), clock=clock)
    f.record(_caught("first"), {"user": 1})
    f.record(_caught())
    f.close()

    assert script.run(["list"], str(tmp_path)) == 0
    out = capsys.readouterr().out
    assert out.startswith("1. ValueError@tests/test_errors.py:_boom  ×2") and "first" in out

    assert script.run(["show", "1"], str(tmp_path)) == 0
    out = capsys.readouterr().out
    assert "message: first" in out and "Traceback" in out and '"user": 1' in out

    assert script.run(["list", "--since", "2030-01-01"], str(tmp_path)) == 0
    assert capsys.readouterr().out == "No errors.\n"
    assert script.run(["show", "2"], str(tmp_path)) == 1
    assert script.run(["list", "--since", "soon"], str(tmp_path)) == 2
