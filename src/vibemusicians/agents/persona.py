"""Agent 2: invent a virtual artist persona.

Each artist is invented once (informed by current trend research, and
optionally a creative-direction hint) and reused for every future song by
that artist, so their catalog reads as one consistent voice rather than a
different personality every run. Persistence lives in db.py — this module is
a pure creative step.
"""

from typing import Any

import anthropic

from vibemusicians import llm

PERSONA_SCHEMA = {
    "type": "object",
    "properties": {
        "name": {"type": "string", "description": "The virtual artist's stage name"},
        "genre": {"type": "string", "description": "Primary genre/sound"},
        "tagline": {"type": "string", "description": "One-sentence hook describing the artist"},
        "backstory": {"type": "string", "description": "2-3 sentence origin story / persona lore"},
        "personality_traits": {
            "type": "array",
            "items": {"type": "string"},
            "description": "4-6 adjectives describing the artist's public persona",
        },
        "vocal_style": {
            "type": "string",
            "description": (
                "Concrete, reusable vocal descriptors for an AI music generator: vocal "
                "register/gender (e.g. 'husky female alto'), timbre and texture (rasp, "
                "breathiness, grit), delivery (conversational vs. belted, phrasing quirks), "
                "and any signature vocal effects/processing. This exact description gets "
                "carried into every song's style prompt so the artist's voice stays "
                "recognizable and consistent from track to track — write it precisely "
                "enough to do that job, not just evocatively."
            ),
        },
        "lyrical_themes": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Recurring subjects/themes this artist writes about",
        },
        "visual_identity": {"type": "string", "description": "Aesthetic, styling, visual motifs"},
        "influences": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Musical influences (for internal creative direction only)",
        },
    },
    "required": [
        "name",
        "genre",
        "tagline",
        "backstory",
        "personality_traits",
        "vocal_style",
        "lyrical_themes",
        "visual_identity",
        "influences",
    ],
    "additionalProperties": False,
}

PERSONA_SYSTEM = """\
You are a creative director inventing a virtual recording artist. Design a \
persona with a distinct, marketable identity — not a generic pop-star \
description. Ground it in what's actually working in music right now (given \
in the trend brief), but give the artist a specific point of view rather than \
chasing every trend at once. The vocal_style must be specific and concrete \
enough to be reused, unchanged, as a style-prompt ingredient for every future \
song by this artist — it is this artist's signature and must not overlap \
with or resemble the vocal identity of another artist on the same roster if \
one is mentioned below.
"""


def invent(
    client: anthropic.Anthropic,
    model: str,
    trend_brief: str,
    direction: str | None = None,
    existing_artists: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    prompt = f"Current music trend brief:\n\n{trend_brief}\n\n"
    if direction:
        prompt += f"Creative direction for this artist: {direction}\n\n"
    if existing_artists:
        roster = "\n".join(
            f"- {a['name']} ({a['genre']}): {a['vocal_style']}" for a in existing_artists
        )
        prompt += (
            "Other artists already on this label's roster (give the new artist a "
            f"clearly distinct voice and lane from these):\n{roster}\n\n"
        )
    prompt += "Invent the artist."

    return llm.structured(client, model, system=PERSONA_SYSTEM, prompt=prompt, schema=PERSONA_SCHEMA)
