"""Small reviewed guidance cards for low-risk, non-diagnostic questions.

Numeric guidance lives here rather than in model prose. These cards are general
education, not a substitute for an individualized clinical assessment.
"""
from __future__ import annotations

import re


GUIDANCE_SOURCES = (
    "https://www.heart.org/en/healthy-living/fitness/fitness-basics/warm-up-cool-down",
    "https://www.nhs.uk/live-well/exercise/how-to-warm-up-before-exercising/",
)


def guidance_reply(topic: str, text: str) -> str:
    lower = (text or "").casefold()
    prior_legs = bool(re.search(r"\blegs?\b.*\byesterday\b|\byesterday\b.*\blegs?\b", lower))
    provenance = "Based on what you just told me—not a recorded workout, " if prior_legs else ""

    if topic in {"warmup", "mobility"}:
        if prior_legs:
            return (
                provenance
                + "keep the warm-up comfortable: 5–10 minutes of easy walking or cycling, "
                "then controlled leg swings, hip circles, and unloaded squats. Save longer "
                "static holds for after activity. If movement causes sharp or worsening pain, "
                "stop rather than pushing through it."
            )
        return (
            "Start with 5–10 minutes of easy movement, then use controlled dynamic movements "
            "that resemble the activity you are about to do. Tell me today’s activity or muscle "
            "group and I’ll choose the matching reviewed warm-up card."
        )
    if topic == "recovery":
        return (
            "Use an easy recovery day when normal movement feels comfortable: light activity, "
            "regular meals and hydration, and adequate sleep. FitKit cannot diagnose pain; stop "
            "training and seek qualified care for sharp, worsening, or unusual symptoms."
        )
    return (
        "Tell me whether you want help with a warm-up, mobility, recovery, or improving an "
        "exercise already in your routine."
    )
