"""Thin helpers around the Anthropic Messages API used by every agent.

Two request shapes cover everything the pipeline needs:
  - `research()`   — a single turn with the web_search tool, for open-ended
                      research where we just want back a text report.
  - `structured()` — a single turn constrained to a JSON schema via
                      `output_config.format`, for everything that needs to
                      come back as data (persona, song brief, ...).

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
        tools=[{"type": "web_search_20260209", "name": "web_search"}],
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
