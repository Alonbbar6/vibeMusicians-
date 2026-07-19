"""Agent 3: turn trend research + persona into a concrete song brief.

Produces everything the Suno generation call needs: title, lyrics (with
[Verse]/[Chorus] structure tags Suno understands), a style prompt, and
negative tags to steer away from unwanted styles.
"""

from typing import Any

import anthropic

from vibemusicians import llm

SONG_SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string", "description": "Song title"},
        "instrumental": {"type": "boolean", "description": "True only if the song should have no vocals"},
        "lyrics": {
            "type": "string",
            "description": (
                "Full lyrics with section tags like [Verse 1], [Chorus], [Bridge], "
                "[Outro]. Empty string if instrumental."
            ),
        },
        "style_prompt": {
            "type": "string",
            "description": (
                "Comma-separated style/production tags for the music generator, "
                "e.g. 'dark pop, moody synths, 90 bpm, female vocals, atmospheric'"
            ),
        },
        "negative_tags": {
            "type": "string",
            "description": "Comma-separated styles/traits to avoid, e.g. 'lo-fi, acoustic, slow ballad'",
        },
        "creative_rationale": {
            "type": "string",
            "description": "1-2 sentences on why this song fits current trends and the artist's persona",
        },
    },
    "required": ["title", "instrumental", "lyrics", "style_prompt", "negative_tags", "creative_rationale"],
    "additionalProperties": False,
}

SONGWRITER_SYSTEM = """\
You are the songwriter and producer for a virtual recording artist. Write one \
complete, original, radio-ready song for them. Maximize the chance this song \
resonates broadly: use structures, hooks, and production direction consistent \
with what's currently working, filtered through the artist's specific persona \
and voice. Lyrics must be wholly original — do not reuse lines, melodies, or \
distinctive phrases from any existing song. The style_prompt is passed \
directly to an AI music generator, so make it dense with concrete, generative \
descriptors (genre, mood, instrumentation, tempo/BPM, vocal type, era/reference \
sound) rather than vague praise words.
"""


def write_song(
    client: anthropic.Anthropic,
    model: str,
    persona: dict[str, Any],
    trend_brief: str,
) -> dict[str, Any]:
    prompt = (
        f"ARTIST PERSONA:\n{persona}\n\n"
        f"CURRENT MUSIC TREND BRIEF:\n{trend_brief}\n\n"
        "Write the next song for this artist."
    )
    return llm.structured(client, model, system=SONGWRITER_SYSTEM, prompt=prompt, schema=SONG_SCHEMA)
