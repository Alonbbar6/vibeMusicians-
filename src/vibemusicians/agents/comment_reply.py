"""Agent 7: reply to a SoundCloud comment in the artist's own voice.

Uses the persona (personality traits, backstory, vocal style, tagline) as
the character sheet so the reply reads like it came from the artist, not a
generic brand account.
"""

from typing import Any

import anthropic

from vibemusicians import llm

REPLY_SYSTEM = """\
You are roleplaying as a virtual recording artist, replying to a fan comment \
on one of your own SoundCloud tracks. Stay fully in character: write the way \
this specific artist would actually talk, using their personality traits and \
backstory as your guide — warm, sarcastic, laid-back, intense, whatever fits \
them. Keep it short (1-3 sentences, like a real comment reply, not an essay). \
Never break character, never mention being an AI, never sound like customer \
service. If the comment is rude, spam, or nonsensical, reply the way the \
artist genuinely would — brief and in character, not scripted.
"""


def write_reply(
    client: anthropic.Anthropic,
    model: str,
    persona: dict[str, Any],
    track_title: str,
    comment_body: str,
    commenter_username: str | None = None,
) -> str:
    who = f"@{commenter_username}" if commenter_username else "a listener"
    prompt = (
        f"ARTIST PERSONA:\n{persona}\n\n"
        f"Your track: \"{track_title}\"\n"
        f"Comment from {who}: \"{comment_body}\"\n\n"
        "Write your reply."
    )
    return llm.chat(client, model, system=REPLY_SYSTEM, prompt=prompt, max_tokens=300)
