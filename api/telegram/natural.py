"""Conservative local routing for common no-slash Telegram messages."""
from __future__ import annotations

from dataclasses import dataclass
import re

from api.telegram.parsing import parse_weight

_FOCUS_NAMES = {
    "leg": "legs", "legs": "legs", "lower body": "lower body",
    "push": "push", "pull": "pull", "upper body": "upper body",
    "chest": "chest", "back": "back", "shoulder": "shoulders",
    "shoulders": "shoulders", "arm": "arms", "arms": "arms", "core": "core",
}


@dataclass(frozen=True)
class NaturalIntent:
    name: str
    argument: str = ""
    outcome: str = "answered"
    reason_code: str | None = None
    source_text: str = ""


def _clean_workout(text: str) -> str:
    return re.sub(
        r"^\s*(?:i\s+(?:did|trained|logged)|we\s+did|log(?:ged)?|workout\s*:?)\s+",
        "", text, flags=re.I,
    ).strip(" .")


def classify_natural(text: str) -> NaturalIntent | None:
    """Return only high-confidence local intents; ambiguity is left to the LLM."""
    value = " ".join((text or "").strip().split())
    lower = value.casefold().rstrip("?!.")
    if not lower:
        return None

    if lower in {"hi", "hello", "hey", "hey there", "good morning", "good afternoon", "good evening"}:
        return NaturalIntent("greeting")
    if lower in {"thanks", "thank you", "sure thanks", "got it thanks", "okay thanks", "ok thanks"}:
        return NaturalIntent("acknowledgement")
    if lower in {"help", "what can you do", "how does this work", "show me what you can do"}:
        return NaturalIntent("help")
    if lower in {
        "what do you remember about me", "what do you know about me", "show my memory",
        "show me my memory", "do you remember my workouts", "what exercises do i usually do",
    }:
        return NaturalIntent("memory_summary")
    if lower in {"cancel", "stop", "never mind", "nevermind"}:
        return NaturalIntent("cancel", outcome="cancelled")
    if lower in {"skip", "later", "not now", "skip this", "skip for now"}:
        return NaturalIntent("skip")
    if lower in {"forget my saved preferences", "forget what i told you", "clear my saved memories", "clear my memory"}:
        return NaturalIntent("memory_clear", outcome="previewed")
    remember_match = re.fullmatch(r"remember\s+(?:that\s+)?(.+)", value, re.I)
    if remember_match:
        content = remember_match.group(1).strip()
        from api.services.memory_service import validate_content
        try:
            validate_content(content)
        except ValueError as exc:
            return NaturalIntent("memory_rejected", str(exc), "clarified", "memory_not_eligible")
        return NaturalIntent("memory_add", content, "previewed")
    if re.fullmatch(r"(?:please\s+)?(?:delete|remove)\s+(?:my\s+)?(?:fitkit\s+)?(?:account|profile|data)", lower):
        return NaturalIntent("delete", outcome="previewed")

    if lower in {
        "planning", "plan", "i'm planning", "i am planning", "plan it",
        "help me plan", "help me plan it", "help me plan this",
    }:
        return NaturalIntent("session_mode", "planning", "advanced")
    if lower in {"logging", "log it", "i'm logging", "i am logging", "finished", "already trained"}:
        return NaturalIntent("session_mode", "logging", "advanced")

    compound_focuses = (
        (r"\bback\s+(?:(?:and|&)\s+)?biceps\b", "back and biceps"),
        (r"\bchest\s+(?:(?:and|&)\s+)?triceps\b", "chest and triceps"),
        (r"\bshoulders\s+(?:(?:and|&)\s+)?arms\b", "shoulders and arms"),
        (r"\blegs\s+(?:(?:and|&)\s+)?core\b", "legs and core"),
    )
    for pattern, focus in compound_focuses:
        if re.search(pattern, lower):
            return NaturalIntent("session_focus", focus, "started")

    focus_match = re.fullmatch(
        r"(?:(?:it(?:'|’)?s|it is)\s+|(?:i(?:'|’)?m|i am)\s+(?:training|doing)\s+)?"
        r"(lower body|upper body|shoulders?|legs?|push|pull|chest|back|arms?|core)"
        r"(?:\s+(?:day|workout|session))?(?:\s+today)?",
        lower,
    )
    if focus_match:
        return NaturalIntent("session_focus", _FOCUS_NAMES[focus_match.group(1)], "started")

    if re.search(r"\b(?:i have|i've got|access to|training at)\s+(?:a\s+)?(?:full\s+)?gym\b", lower):
        return NaturalIntent("session_equipment", "gym", "advanced")
    if re.search(r"\b(?:at home|home gym|dumbbells? only|bodyweight only)\b", lower):
        equipment = "dumbbells" if "dumbbell" in lower else ("bodyweight" if "bodyweight" in lower else "home")
        return NaturalIntent("session_equipment", equipment, "advanced")

    if re.search(r"\b(warm[ -]?up|stretch(?:ing|es)?|mobility)\b", lower):
        topic = "mobility" if "mobility" in lower else "warmup"
        return NaturalIntent("guidance", topic, source_text=value)

    if re.fullmatch(r"(?:show|open|give me)\s+(?:my\s+)?dashboard|(?:my\s+)?dashboard", lower):
        return NaturalIntent("dashboard")
    if re.fullmatch(r"(?:connect|set up|setup|link)\s+(?:my\s+)?health(?:\s+data)?", lower):
        return NaturalIntent("connect_health")
    if re.fullmatch(r"(?:show|what(?:'s| is)|how(?:'s| is))\s+(?:my\s+)?(?:health|recovery)(?:\s+today)?|(?:health|recovery)(?:\s+summary)?", lower):
        return NaturalIntent("health")
    if re.fullmatch(r"(?:what(?:'s| is)\s+)?(?:on\s+)?(?:my\s+)?(?:today|today's summary)|what did i do today|show today|what was my last workout", lower):
        return NaturalIntent("today")
    if re.fullmatch(r"(?:show\s+)?(?:my\s+)?progress|how am i doing|how(?:'s| is) my progress|show my weight trend", lower):
        return NaturalIntent("progress")
    if re.fullmatch(r"(?:show\s+)?(?:my\s+)?profile|what(?:'s| is) in my profile", lower):
        return NaturalIntent("profile")
    if re.fullmatch(r"(?:show\s+)?(?:my\s+)?goals?|what are my goals", lower):
        return NaturalIntent("goals")

    match = re.fullmatch(r"(?:what should i (?:do|lift) (?:for\s+)?|recommend(?:ation)?\s+(?:for\s+)?|recommend\s+)(.+?)(?:\s+next)?", lower)
    if match and match.group(1) not in {"today", "next"}:
        return NaturalIntent("recommend", match.group(1).strip())

    match = re.fullmatch(r"(?:i am|i'm|my sex is)\s+(male|female)", lower)
    if match:
        return NaturalIntent("profile_update", f"sex {match.group(1)}", "previewed")
    match = re.fullmatch(r"(?:i am|i'm|my age is)\s+(\d{1,3})(?:\s+years? old)?", lower)
    if match:
        return NaturalIntent("profile_update", f"age {match.group(1)}", "previewed")
    match = re.fullmatch(r"my resting (?:heart rate|hr) is\s+(\d{1,3})", lower)
    if match:
        return NaturalIntent("profile_update", f"resting_hr {match.group(1)}", "previewed")
    match = re.fullmatch(r"my (?:max|maximum) (?:heart rate|hr) is\s+(\d{1,3})", lower)
    if match:
        return NaturalIntent("profile_update", f"max_hr {match.group(1)}", "previewed")

    match = re.fullmatch(r"(?:i want to weigh|set (?:my )?weight goal (?:to|at)|my goal (?:is|is to weigh))\s+(\d+(?:\.\d+)?)\s*(kg|kgs|lb|lbs)(?:\s+by\s+(\d{4}-\d{2}-\d{2}))?", lower)
    if match:
        suffix = f" by {match.group(3)}" if match.group(3) else ""
        return NaturalIntent("goal_add", f"weight {match.group(1)} {match.group(2)}{suffix}", "previewed")
    match = re.fullmatch(r"(?:i want to |my goal is to )?(?:train|work out|workout)\s+(\d{1,2})\s+(?:times|sessions?)\s+(?:per|a)\s+week", lower)
    if match:
        return NaturalIntent("goal_add", f"frequency {match.group(1)} per week", "previewed")

    match = re.fullmatch(r"(?:turn|switch|set)\s+(?:ai|flexible chat|natural conversation)\s+(on|off)", lower)
    if match:
        return NaturalIntent("ai_preference", match.group(1), "previewed" if match.group(1) == "on" else "completed")

    match = re.fullmatch(
        r"(?:set\s+)?(?:my\s+)?(?:target\s+(?:for\s+)?|)(.+?)\s+(?:target\s+)?(?:to\s+)?(\d+)\s+reps"
        r"(?:\s+(?:with\s+)?(?:an?\s+)?increment(?:\s+of)?\s+(\d+(?:\.\d+)?)\s*(kg|lb))?",
        lower,
    )
    if match and any(word in lower for word in ("target", "increment")):
        suffix = f" increment {match.group(3)} {match.group(4)}" if match.group(3) else ""
        return NaturalIntent("target", f"{match.group(1)} {match.group(2)} reps{suffix}", "previewed")

    match = re.fullmatch(r"(?:correct|fix|edit)\s+(?:workout\s+)?([0-9a-f]{8}-[0-9a-f-]{27,})", lower)
    if match:
        return NaturalIntent("correct_workout", match.group(1), "previewed")

    if parse_weight(value) is not None:
        return NaturalIntent("weight", value, "previewed")

    workout = _clean_workout(value)
    has_sets = bool(re.search(r"\b\d+\s*(?:x|×|\*)\s*\d+\b|\b\d+\s+sets?\s+(?:of\s+)?\d+(?:\s+reps?)?\b|\bfor\s+\d", workout, re.I))
    has_load = bool(re.search(r"\b\d+(?:\.\d+)?\s*(?:kg|kgs|lb|lbs|pounds?)\b|\bbodyweight\b", workout, re.I))
    if has_sets and has_load:
        return NaturalIntent("workout", workout, "previewed")
    if has_sets and re.search(r"[a-z]", workout, re.I):
        return NaturalIntent("workout_missing_load", workout, "clarified", "missing_workout_load")

    return None
