"""Runs the full pipeline end to end: research -> persona -> song -> audio ->
publish. Each stage persists its result to SQLite as it completes, so a
failure partway through (e.g. SoundCloud is down) doesn't lose the generated
track — rerunning `vibemusicians publish <track-id>` can pick it up later.
"""

import logging
from dataclasses import dataclass

import anthropic

from vibemusicians import db
from vibemusicians.agents import cover_art, distribution, music_generation, persona, songwriter, trend_research
from vibemusicians.config import Settings
from vibemusicians.providers.image import ImageClient
from vibemusicians.providers.soundcloud import SoundCloudClient
from vibemusicians.providers.suno import SunoClient

log = logging.getLogger("vibemusicians")


@dataclass
class RunResult:
    track_id: int
    title: str
    audio_path: str
    cover_art_path: str
    soundcloud_url: str | None


class UploadLimitReached(RuntimeError):
    """Raised when an artist's weekly SoundCloud upload cap has already been hit."""


class ArtistNotFound(RuntimeError):
    pass


class AmbiguousArtist(RuntimeError):
    pass


class RosterFull(RuntimeError):
    """Raised when adding a new artist would exceed MAX_ARTISTS."""


def run_pipeline(
    settings: Settings,
    publish: bool = True,
    private: bool = True,
    artist_name: str | None = None,
    new_artist: bool = False,
    direction: str | None = None,
) -> RunResult:
    roster = db.list_artists(settings.db_path)

    resolved_artist: dict | None = None
    if artist_name:
        resolved_artist = next(
            (a for a in roster if a["name"].lower() == artist_name.lower()), None
        )
        if not resolved_artist:
            available = ", ".join(a["name"] for a in roster) or "(none yet)"
            raise ArtistNotFound(f"No artist named {artist_name!r}. Available: {available}")
    elif not new_artist:
        if len(roster) == 1:
            resolved_artist = roster[0]
        elif len(roster) > 1:
            names = ", ".join(a["name"] for a in roster)
            raise AmbiguousArtist(
                f"Multiple artists on the roster ({names}). Pass --artist NAME to pick one, "
                "or --new-artist to add another."
            )
        # len(roster) == 0: fall through and invent the first one below.

    if resolved_artist is None and len(roster) >= settings.max_artists:
        raise RosterFull(
            f"Roster is full ({len(roster)}/{settings.max_artists} artists). Adjust MAX_ARTISTS "
            "in .env to allow more, or pick an existing artist with --artist."
        )

    if publish and resolved_artist:
        recent = db.count_recent_publishes(settings.db_path, resolved_artist["id"], days=7)
        if recent >= settings.weekly_upload_limit:
            raise UploadLimitReached(
                f"Weekly upload limit reached for {resolved_artist['name']}: "
                f"{recent}/{settings.weekly_upload_limit} tracks published to SoundCloud in the "
                "last 7 days. Skipping this run to avoid going over. Adjust WEEKLY_UPLOAD_LIMIT "
                "in .env to change the cap."
            )

    claude = anthropic.Anthropic(api_key=settings.anthropic_api_key)

    log.info("Researching current music trends...")
    trend_brief = trend_research.run(claude, settings.claude_model)

    if resolved_artist:
        artist = resolved_artist
        log.info("Using existing artist: %s (%s)", artist["name"], artist["genre"])
    else:
        log.info("Inventing a new artist persona...")
        invented = persona.invent(
            claude, settings.claude_model, trend_brief, direction=direction, existing_artists=roster
        )
        artist_id = db.create_artist(settings.db_path, invented)
        invented["id"] = artist_id
        artist = invented
        log.info("New artist: %s (%s)", artist["name"], artist["genre"])

    log.info("Writing song...")
    song = songwriter.write_song(claude, settings.claude_model, artist, trend_brief)
    log.info("Song: %s", song["title"])

    track_id = db.create_track(
        settings.db_path,
        db.Track(
            artist_id=artist["id"],
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
    suno = SunoClient(
        settings.suno_api_base_url,
        settings.suno_api_key or "",
        settings.suno_model,
        callback_url=settings.suno_callback_url,
    )
    task_id, audio_path = music_generation.generate(suno, song, settings.tracks_dir, track_id)
    db.update_track(settings.db_path, track_id, suno_task_id=task_id, audio_path=audio_path, status="generated")
    log.info("Audio saved to %s", audio_path)

    log.info("Generating cover art...")
    image_client = ImageClient(
        settings.suno_api_base_url, settings.suno_api_key or "", callback_url=settings.suno_callback_url
    )
    cover_art_path = cover_art.generate(image_client, artist, song, settings.tracks_dir, track_id)
    db.update_track(settings.db_path, track_id, cover_art_path=cover_art_path)
    log.info("Cover art saved to %s", cover_art_path)

    soundcloud_url = None
    if publish:
        log.info("Publishing to SoundCloud...")
        soundcloud = SoundCloudClient(
            client_id=settings.soundcloud_client_id or "",
            client_secret=settings.soundcloud_client_secret or "",
            refresh_token=settings.soundcloud_refresh_token or "",
        )
        result = distribution.publish(
            soundcloud, audio_path, song, artist, private=private, artwork_path=cover_art_path
        )
        soundcloud_url = result.get("permalink_url")
        db.update_track(
            settings.db_path,
            track_id,
            soundcloud_track_id=str(result.get("id", "")),
            soundcloud_url=soundcloud_url,
            status="published",
        )
        log.info("Published: %s", soundcloud_url)

    return RunResult(
        track_id=track_id,
        title=song["title"],
        audio_path=audio_path,
        cover_art_path=cover_art_path,
        soundcloud_url=soundcloud_url,
    )
