"""Agent 6: generate unique cover art for a track.

Built deterministically from the artist's persona (visual_identity keeps
every cover on-brand for that artist) plus the specific song (title/rationale
keeps each cover unique) — no extra LLM call needed, just string assembly.
"""

from pathlib import Path
from typing import Any

from vibemusicians.providers.gemini_image import GeminiImageClient

_EXTENSION_BY_MIME_TYPE = {"image/png": ".png", "image/jpeg": ".jpg", "image/webp": ".webp"}


def build_prompt(persona: dict[str, Any], song: dict[str, Any]) -> str:
    return (
        f"Album cover art, square format, professional record label quality. "
        f"Visual identity: {persona.get('visual_identity', '')}. "
        f"For a {persona.get('genre', '')} song titled \"{song['title']}\". "
        f"Mood and theme: {song.get('creative_rationale', '')}. "
        "No text, no words, no letters, no logos anywhere in the image."
    )


def generate(image_client: GeminiImageClient, persona: dict[str, Any], song: dict[str, Any], output_dir: Path, track_id: int) -> str:
    """Generate cover art for `song`. Returns the saved file path."""
    prompt = build_prompt(persona, song)
    image = image_client.generate(prompt)

    extension = _EXTENSION_BY_MIME_TYPE.get(image.mime_type, ".png")
    destination = output_dir / f"{track_id:04d}_cover{extension}"
    image_client.download(image, str(destination))
    return str(destination)
