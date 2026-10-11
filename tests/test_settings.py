import pytest

from settings.registry import (
    SNOOZE_OPTIONS, format_minutes, parse_snooze_options, validate_snooze_options,
)


@pytest.mark.parametrize("text, expected", [
    ("10m, 1h, 3h",               [10, 60, 180]),
    ("5, 15, 60",                 [5, 15, 60]),
    ("5 15 60",                   [5, 15, 60]),
    ("10m 1h",                    [10, 60]),
    ("10 min, 1 hour",            [10, 60]),
    ("half an hour and 2 hours",  [30, 120]),
    ("1h30m",                     [90]),
    ("60, 10",                    [10, 60]),       # sorted
    ("10, 10m, 1h",               [10, 60]),       # de-duplicated
    ("24h",                       [1440]),
])
def test_parse_snooze_options(text, expected):
    assert parse_snooze_options(text) == expected


@pytest.mark.parametrize("text, message", [
    ("",                    "at least one"),
    ("soon",                "don't understand"),
    ("5, 10, 15, 20",       "At most 3"),
    ("0",                   "between 1 minute and 24 hours"),
    ("25h",                 "between 1 minute and 24 hours"),
    ("30 seconds",          "whole number of minutes"),
])
def test_parse_snooze_options_errors(text, message):
    with pytest.raises(ValueError, match=message):
        parse_snooze_options(text)


@pytest.mark.parametrize("value", [None, [], "10", [10.5], [True], [1, 2, 3, 4]])
def test_validate_rejects(value):
    with pytest.raises(ValueError):
        validate_snooze_options(value)


@pytest.mark.parametrize("minutes, expected", [
    (5, "5 min"), (60, "1 h"), (90, "1 h 30 min"), (1440, "24 h"),
])
def test_format_minutes(minutes, expected):
    assert format_minutes(minutes) == expected


def test_default_is_valid():
    assert validate_snooze_options(SNOOZE_OPTIONS.default) == SNOOZE_OPTIONS.default


# --- repository -------------------------------------------------------------

def test_repository_default_set_reset(user):
    from db.repository.settings_repository import SettingsRepository
    from db.db import SessionLocal
    from models.user_setting import UserSetting

    repo = SettingsRepository()
    assert repo.get(user.id, SNOOZE_OPTIONS) == [10, 60]

    assert repo.set(user.id, SNOOZE_OPTIONS, [60, 5]) == [5, 60]
    assert repo.get(user.id, SNOOZE_OPTIONS) == [5, 60]

    repo.set(user.id, SNOOZE_OPTIONS, [5, 15, 60])
    assert repo.get(user.id, SNOOZE_OPTIONS) == [5, 15, 60]

    # Setting the default removes the row: only differences are stored.
    repo.reset(user.id, SNOOZE_OPTIONS)
    assert repo.get(user.id, SNOOZE_OPTIONS) == [10, 60]
    with SessionLocal() as s:
        assert s.get(UserSetting, (user.id, SNOOZE_OPTIONS.key)) is None


def test_repository_rejects_invalid(user):
    from db.repository.settings_repository import SettingsRepository

    repo = SettingsRepository()
    with pytest.raises(ValueError):
        repo.set(user.id, SNOOZE_OPTIONS, [0])
    assert repo.get(user.id, SNOOZE_OPTIONS) == [10, 60]


def test_repository_invalid_stored_value_falls_back(user):
    from db.repository.settings_repository import SettingsRepository
    from db.db import SessionLocal
    from models.user_setting import UserSetting

    with SessionLocal() as s:
        s.add(UserSetting(user_id=user.id, key=SNOOZE_OPTIONS.key, value=[1, 2, 3, 4, 5]))
        s.commit()
    assert SettingsRepository().get(user.id, SNOOZE_OPTIONS) == [10, 60]


def test_repository_get_for_users(db):
    from db.repository.settings_repository import SettingsRepository
    from db.repository.user_repository import UserRepository

    a, b = UserRepository().get_or_create(111), UserRepository().get_or_create(222)
    repo = SettingsRepository()
    repo.set(a.id, SNOOZE_OPTIONS, [5])
    assert repo.get_for_users([a.id, b.id, a.id], SNOOZE_OPTIONS) == {a.id: [5], b.id: [10, 60]}
