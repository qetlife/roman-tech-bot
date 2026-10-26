"""What the assistant can do, in one list (#61).

The web app's home ("What I can do"), the reply to "what can you do?" and
its suggestions all come from here, so a new skill shows up everywhere once
it's added. Each example must be a phrase the bot understands.
"""

from    dataclasses     import dataclass

from    enums           import Skill


@dataclass(frozen=True)
class SkillInfo:
    skill: Skill
    emoji: str          # in Telegram's text; the web app has its own icons
    title: str
    summary: str
    examples: tuple


SKILLS = (
    SkillInfo(Skill.REMINDERS, "⏰", "Reminders", "One-off or repeating, by text or voice",
              ("every monday at 8 to take out the bins", "remind me in 2 hours to call mom")),
    SkillInfo(Skill.EVENTS, "📅", "Events", "Plans, with reminders before them",
              ("event padel on thursday at 19:00", "what do I have tomorrow?")),
    SkillInfo(Skill.PEOPLE, "👥", "People", "Remind someone else",
              ("remind anna tomorrow at 9 to bring the keys",)),
    SkillInfo(Skill.CALENDAR, "🔄", "Google Calendar", "Your events, synced both ways",
              ("what's on my calendar",)),
)


def available(calendar: bool) -> list:
    """The skills this bot has: Google Calendar only where it's set up."""
    return [s for s in SKILLS if calendar or s.skill != Skill.CALENDAR]


def describe(skills: list) -> str:
    """The reply to "what can you do?"."""
    lines = ["Here's what I can do:"]
    for s in skills:
        lines.append(f"\n{s.emoji} {s.title}: {s.summary[0].lower()}{s.summary[1:]}.\n“{s.examples[0]}”")
    return "\n".join(lines)
