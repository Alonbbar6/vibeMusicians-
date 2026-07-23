"""Thin helpers around the Anthropic Messages API used by every agent.

Three request shapes cover everything the pipeline needs:
  - `research()`   — a single turn with the web_search tool, for open-ended
                      research where we just want back a text report.
  - `structured()` — a single turn constrained to a JSON schema via
                      `output_config.format`, for everything that needs to
                      come back as data (persona, song brief, ...).
  - `chat()`        — a single plain-text turn with a system prompt, for
                      short free-text generation (comment replies) that
                      doesn't need tools or a schema.

These are kept separate because structured outputs are incompatible with
citations and don't mix well with an open-ended tool loop — splitting research
(free text) from extraction (schema-constrained) avoids that entirely.
"""

import json
from typing import Any

import anthropic


def research(client: anthropic.Anthropic, model: str, prompt: str) -> str:
    """Ask Claude to research something on the web and return prose."""
    response = client.messages.create(
        model=model,
        max_tokens=4096,
        # max_uses bounds how many searches (and how much scraped page content)
        # a single call can pull in — without it, nothing stops the model from
        # using all 10 server-side rounds every time, each one adding page
        # content to the bill.
        tools=[{"type": "web_search_20260209", "name": "web_search", "max_uses": 4}],
        messages=[{"role": "user", "content": prompt}],
    )
    parts = [block.text for block in response.content if block.type == "text"]
    return "\n".join(parts).strip()


def chat(client: anthropic.Anthropic, model: str, system: str, prompt: str, max_tokens: int = 512) -> str:
    """Ask Claude for a short plain-text response — no tools, no schema."""
    response = client.messages.create(
        model=model,
        max_tokens=max_tokens,
        system=system,
        messages=[{"role": "user", "content": prompt}],
    )
    parts = [block.text for block in response.content if block.type == "text"]
    return "\n".join(parts).strip()


def structured(
    client: anthropic.Anthropic,
    model: str,
    system: str,
    prompt: str,
    schema: dict[str, Any],
) -> dict[str, Any]:
    """Ask Claude for a JSON object matching `schema`."""
    response = client.messages.create(
        model=model,
        max_tokens=4096,
        system=system,
        output_config={"format": {"type": "json_schema", "schema": schema}},
        messages=[{"role": "user", "content": prompt}],
    )
    text = next(block.text for block in response.content if block.type == "text")
    return json.loads(text)
