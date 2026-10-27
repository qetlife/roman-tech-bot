"""The web app as an assistant (#61): the briefing's sentences, the skills list, and reports outside the web app."""

from datetime   import datetime
from types      import SimpleNamespace
from zoneinfo   import ZoneInfo

from telegram   import Update

from core.briefing  import greeting, left_today, today_text, tomorrow_text
from core.skills    import SKILLS, available, describe
from enums          import CardKind, Skill
from handlers       import report


NOW = datetime(2026, 10, 26, 17, 42, tzinfo=ZoneInfo("Europe/Lisbon"))


def item(time, text, kind="reminder"):
    return {"kind": kind, "time": time, "text": text}


def test_greeting():
    assert greeting(NOW, "Roman") == "Good afternoon, Roman"
    assert greeting(NOW.replace(hour=8)) == "Good morning"
    assert greeting(NOW.replace(hour=18)) == "Good evening"
    assert greeting(NOW.replace(hour=2)) == "Good evening"


def test_what_is_left_today():
    items = [item(None, "holiday", "event"), item("09:00", "dentist"), item("19:00", "padel", "event"),
             item("21:00", "call mom")]
    left = left_today(items, NOW)
    assert [i["text"] for i in left] == ["holiday", "padel", "call mom"]
    assert today_text(left, NOW) == "3 things left today. padel is next, at 19:00, in 1 h 18 min."
    assert today_text(left[2:], NOW) == "One thing left today: call mom at 21:00, in 3 h 18 min."
    assert today_text([], NOW) == "Nothing else today."
    assert today_text(left[:1], NOW) == "One thing today: holiday, all day."
    assert today_text([left[0], left[0]], NOW) == "2 things today, all day."
    assert today_text([item("17:42", "now")], NOW) == "One thing left today: now at 17:42, now."


def test_tomorrow():
    assert tomorrow_text([]) == "Tomorrow is free."
    assert tomorrow_text([item("09:00", "dentist")]) == "Tomorrow starts at 09:00 with dentist."
    assert tomorrow_text([item(None, "trip"), item("09:00", "dentist"), item("21:00", "padel")]) == \
        "Tomorrow starts at 09:00 with dentist, 3 things in all."
    assert tomorrow_text([item(None, "trip")]) == "Tomorrow: trip, all day."


def test_skills():
    assert Skill.CALENDAR not in [s.skill for s in available(calendar=False)]
    assert [s.skill for s in available(calendar=True)] == [s.skill for s in SKILLS]
    text = describe(available(calendar=False))
    assert text.startswith("Here's what I can do:\n\n⏰ Reminders: one-off or repeating, by text or voice.\n")
    assert "“remind anna tomorrow at 9 to bring the keys”" in text


def test_reports_do_nothing_outside_the_web_app():
    for update in (Update(update_id=1), SimpleNamespace()):
        report.step(update, "Saved")
        report.card(update, SimpleNamespace(message_id=1), CardKind.REMINDER, title="x")


def test_a_report():
    update = SimpleNamespace(report=report.Report())
    report.step(update, "Saved")
    report.card(update, SimpleNamespace(message_id=-5), CardKind.EVENT, title="padel")
    report.card(update, None, CardKind.EVENT, title="nothing to show it on")
    assert update.report.steps == ["Saved"]
    assert update.report.cards == {-5: {"kind": CardKind.EVENT, "title": "padel"}}


def test_times_in_steps():
    assert report.when("Tomorrow, 09:00 (in 9 h 30 min)") == "tomorrow at 09:00"
    assert report.when("Today, 21:00 (in 2 h)") == "today at 21:00"
    assert report.when("Mon 02 Nov, 08:00 (in 6 d 9 h)") == "Mon 02 Nov at 08:00"
    assert report.when("Fri 30 Oct, 19:00–20:30 (in 3 d)") == "Fri 30 Oct at 19:00–20:30"
    assert report.when("Thu 23 Oct (all day)") == "Thu 23 Oct (all day)"
