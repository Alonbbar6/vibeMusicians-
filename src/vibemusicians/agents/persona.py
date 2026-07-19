"""Agent 2: invent and persist a virtual artist persona.

The persona is created once (informed by the current trend research) and then
reused for every future song, so the catalog reads as one consistent artist
rather than a different voice every run. Stored in SQLite via db.py.
"""

from pathlib import Path
from typing import Any

import anthropic

from vibemusicians import db, llm

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
        "vocal_style": {"type": "string", "description": "How the artist's voice/delivery sounds"},
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
chasing every trend at once.
"""


def get_or_create(
    client: anthropic.Anthropic,
    model: str,
    db_path: Path,
    trend_brief: str,
) -> dict[str, Any]:
    existing = db.load_persona(db_path)
    if existing:
        return existing

    persona = llm.structured(
        client,
        model,
        system=PERSONA_SYSTEM,
        prompt=f"Current music trend brief:\n\n{trend_brief}\n\nInvent the artist.",
        schema=PERSONA_SCHEMA,
    )
    db.save_persona(db_path, persona)
    return persona
