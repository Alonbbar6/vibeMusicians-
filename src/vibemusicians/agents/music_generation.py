"""Agent 4: turn a song brief into an actual audio file via Suno."""

from pathlib import Path
from typing import Any

from vibemusicians.providers.suno import SunoClient


def generate(suno: SunoClient, song: dict[str, Any], output_dir: Path, track_id: int) -> tuple[str, str]:
    """Generate audio for `song`. Returns (task_id, audio_file_path)."""
    task_id = suno.generate(
        title=song["title"],
        style=song["style_prompt"],
        lyrics=song["lyrics"],
        instrumental=song["instrumental"],
        negative_tags=song.get("negative_tags"),
    )
    tracks = suno.wait_for_completion(task_id)
    best = tracks[0]

    safe_title = "".join(c for c in song["title"] if c.isalnum() or c in " -_").strip() or "track"
    destination = output_dir / f"{track_id:04d}_{safe_title}.mp3"
    suno.download(best, str(destination))
    return task_id, str(destination)
