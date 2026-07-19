"""Runs the full pipeline end to end: research -> persona -> song -> audio ->
publish. Each stage persists its result to SQLite as it completes, so a
failure partway through (e.g. SoundCloud is down) doesn't lose the generated
track — rerunning `vibemusicians publish <track-id>` can pick it up later.
"""

import logging
from dataclasses import dataclass

import anthropic

from vibemusicians import db
from vibemusicians.agents import distribution, music_generation, persona, songwriter, trend_research
from vibemusicians.config import Settings
from vibemusicians.providers.soundcloud import SoundCloudClient
from vibemusicians.providers.suno import SunoClient

log = logging.getLogger("vibemusicians")


@dataclass
class RunResult:
    track_id: int
    title: str
    audio_path: str
    soundcloud_url: str | None


def run_pipeline(settings: Settings, publish: bool = True, private: bool = True) -> RunResult:
    claude = anthropic.Anthropic(api_key=settings.anthropic_api_key)

    log.info("Researching current music trends...")
    trend_brief = trend_research.run(claude, settings.claude_model)

    log.info("Loading/creating artist persona...")
    artist = persona.get_or_create(claude, settings.claude_model, settings.db_path, trend_brief)
    log.info("Artist: %s (%s)", artist["name"], artist["genre"])

    log.info("Writing song...")
    song = songwriter.write_song(claude, settings.claude_model, artist, trend_brief)
    log.info("Song: %s", song["title"])

    track_id = db.create_track(
        settings.db_path,
        db.Track(
            title=song["title"],
            lyrics=song["lyrics"],
            style_prompt=song["style_prompt"],
            negative_tags=song.get("negative_tags"),
            instrumental=song["instrumental"],
            trend_brief=trend_brief,
            status="generating",
        ),
    )

    log.info("Generating audio with Suno (this can take a few minutes)...")
    suno = SunoClient(settings.suno_api_base_url, settings.suno_api_key or "", settings.suno_model)
    task_id, audio_path = music_generation.generate(suno, song, settings.tracks_dir, track_id)
    db.update_track(settings.db_path, track_id, suno_task_id=task_id, audio_path=audio_path, status="generated")
    log.info("Audio saved to %s", audio_path)

    soundcloud_url = None
    if publish:
        log.info("Publishing to SoundCloud...")
        soundcloud = SoundCloudClient(
            client_id=settings.soundcloud_client_id or "",
            client_secret=settings.soundcloud_client_secret or "",
            refresh_token=settings.soundcloud_refresh_token or "",
        )
        result = distribution.publish(soundcloud, audio_path, song, artist, private=private)
        soundcloud_url = result.get("permalink_url")
        db.update_track(
            settings.db_path,
            track_id,
            soundcloud_track_id=str(result.get("id", "")),
            soundcloud_url=soundcloud_url,
            status="published",
        )
        log.info("Published: %s", soundcloud_url)

    return RunResult(track_id=track_id, title=song["title"], audio_path=audio_path, soundcloud_url=soundcloud_url)
