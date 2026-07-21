"""Agent 5: publish the finished track to SoundCloud.

v1 targets SoundCloud only — it has a real public upload API. Apple Music and
Spotify don't offer one for individual artists; real releases there require a
distributor (DistroKid, TuneCore, CD Baby, ...). To add one later, give it the
same (audio_path, title, persona, song) -> url signature as `publish` below
and call it alongside this from the orchestrator.
"""

from typing import Any

from vibemusicians.providers.soundcloud import SoundCloudClient


def publish(
    soundcloud: SoundCloudClient,
    audio_path: str,
    song: dict[str, Any],
    persona: dict[str, Any],
    private: bool = True,
    artwork_path: str | None = None,
) -> dict[str, Any]:
    description = (
        f"{song.get('creative_rationale', '')}\n\n"
        f"feat. {persona['name']} ({persona['genre']})"
    ).strip()
    tag_list = " ".join(f'"{tag.strip()}"' for tag in song["style_prompt"].split(",") if tag.strip())

    return soundcloud.upload_track(
        audio_path=audio_path,
        title=f"{song['title']} (feat. {persona['name']})",
        description=description,
        tag_list=tag_list,
        genre=persona.get("genre", ""),
        private=private,
        artwork_path=artwork_path,
    )
