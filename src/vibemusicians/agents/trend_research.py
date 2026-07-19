"""Agent 1: research what's currently popular in music.

Uses Claude's web_search tool to pull together a snapshot of current charts,
breakout artists, and trending sounds/production styles. Returns free text —
the songwriter agent turns this into concrete creative direction.
"""

import anthropic

from vibemusicians import llm

RESEARCH_PROMPT = """\
Research current music trends so an artist team can write a song likely to \
resonate with listeners right now. Look at:

- Current Billboard Hot 100 / Spotify Top 50 / Apple Music top charts
- Breakout or fast-rising artists in the last 1-3 months
- Recurring sonic trends: tempo ranges, production styles, vocal processing,
  song structures, lyrical themes that are working right now
- Which genres/subgenres are gaining momentum vs fading

Summarize your findings as a concise brief (bullet points are fine) covering:
1. 3-5 genres/sounds that are currently hot, with why
2. Common lyrical themes and moods in current hits
3. Typical tempo/production choices in those hits
4. One or two specific rising artists worth taking style cues from (for \
   inspiration only, not imitation)

Be specific and current — this is being used today, so prioritize recent \
information over general music knowledge.
"""


def run(client: anthropic.Anthropic, model: str) -> str:
    return llm.research(client, model, RESEARCH_PROMPT)
