"""Runs the full pipeline end to end: research -> persona -> song -> audio ->
publish. Each stage persists its result to SQLite as it completes, so a
failure partway through (e.g. SoundCloud is down) doesn't lose the generated
track — rerunning `vibemusicians publish <track-id>` can pick it up later.
"""

import logging
from dataclasses import dataclass

import anthropic

from vibemusicians import db, env_file
from vibemusicians.agents import cover_art, distribution, music_generation, persona, songwriter, trend_research
from vibemusicians.config import Settings
from vibemusicians.providers.gemini_image import GeminiImageClient
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


class TrackNotReady(RuntimeError):
    """Raised when a track can't be published yet (missing audio/art) or already was."""


def _soundcloud_client(settings: Settings) -> SoundCloudClient:
    def _persist_rotated_token(new_token: str, settings: Settings = settings) -> None:
        # Update in-memory settings immediately too, not just the file — a
        # single process can make several SoundCloud calls in one run, and the
        # next one must not hand SoundCloud the now-invalidated old token
        # still sitting in this already-loaded settings object.
        settings.soundcloud_refresh_token = new_token
        env_file.upsert("SOUNDCLOUD_REFRESH_TOKEN", new_token)
        settings.soundcloud_token_path.write_text(new_token)

    return SoundCloudClient(
        client_id=settings.soundcloud_client_id or "",
        client_secret=settings.soundcloud_client_secret or "",
        refresh_token=settings.soundcloud_refresh_token or "",
        on_token_rotated=_persist_rotated_token,
    )


def set_track_sharing(settings: Settings, track_id: int, private: bool) -> None:
    """Flip an already-published track's SoundCloud visibility."""
    track = db.get_track(settings.db_path, track_id)
    if not track:
        raise TrackNotReady(f"No track #{track_id}.")
    if not track.get("soundcloud_track_id"):
        raise TrackNotReady(f"Track #{track_id} hasn't been published yet.")

    soundcloud = _soundcloud_client(settings)
    soundcloud.set_sharing(track["soundcloud_track_id"], private=private)


def resume_track(settings: Settings, track_id: int, publish: bool = True, private: bool = True) -> RunResult:
    """Finish an interrupted track — pick up from whichever stage it stopped at
    (Suno audio, cover art, or SoundCloud publish) using the song/artist data
    already stored, without repeating trend research or songwriting. Fixes
    tracks orphaned by a crash or a killed process mid-run.
    """
    track = db.get_track(settings.db_path, track_id)
    if not track:
        raise TrackNotReady(f"No track #{track_id}.")
    if track["status"] == "published":
        raise TrackNotReady(f"Track #{track_id} is already published.")

    artist = db.get_artist(settings.db_path, track["artist_id"])
    if not artist:
        raise TrackNotReady(f"Track #{track_id} has no associated artist.")

    song = {
        "title": track["title"],
        "lyrics": track.get("lyrics"),
        "style_prompt": track["style_prompt"],
        "negative_tags": track.get("negative_tags"),
        "instrumental": bool(track.get("instrumental")),
        "creative_rationale": track.get("creative_rationale") or "",
    }

    audio_path = track.get("audio_path")
    if not audio_path:
        log.info("Resuming track #%s: generating audio with Suno...", track_id)
        suno = SunoClient(
            settings.suno_api_base_url,
            settings.suno_api_key or "",
            settings.suno_model,
            callback_url=settings.suno_callback_url,
        )
        task_id, audio_path = music_generation.generate(suno, song, settings.tracks_dir, track_id)
        db.update_track(settings.db_path, track_id, suno_task_id=task_id, audio_path=audio_path, status="generated")

    cover_art_path = track.get("cover_art_path")
    if not cover_art_path:
        log.info("Resuming track #%s: generating cover art...", track_id)
        image_client = GeminiImageClient(settings.gemini_api_key or "", model=settings.gemini_image_model)
        cover_art_path = cover_art.generate(image_client, artist, song, settings.tracks_dir, track_id)
        db.update_track(settings.db_path, track_id, cover_art_path=cover_art_path)

    soundcloud_url = track.get("soundcloud_url")
    if publish and not soundcloud_url:
        log.info("Resuming track #%s: publishing to SoundCloud...", track_id)
        soundcloud_url = publish_track(settings, track_id, private=private)

    return RunResult(
        track_id=track_id,
        title=track["title"],
        audio_path=audio_path,
        cover_art_path=cover_art_path,
        soundcloud_url=soundcloud_url,
    )


def publish_track(settings: Settings, track_id: int, private: bool = True) -> str | None:
    """Publish an already-generated track to SoundCloud. Used both right after
    generation (run_pipeline) and later on demand (dashboard's Publish button) —
    kept as one function so both paths get the same rotating-token handling.
    """
    track = db.get_track(settings.db_path, track_id)
    if not track:
        raise TrackNotReady(f"No track #{track_id}.")
    if track["status"] == "published":
        raise TrackNotReady(f"Track #{track_id} is already published.")
    if not track.get("audio_path") or not track.get("cover_art_path"):
        raise TrackNotReady(f"Track #{track_id} isn't fully generated yet (missing audio or cover art).")

    artist = db.get_artist(settings.db_path, track["artist_id"])
    if not artist:
        raise TrackNotReady(f"Track #{track_id} has no associated artist.")

    song = {
        "title": track["title"],
        "lyrics": track.get("lyrics"),
        "style_prompt": track["style_prompt"],
        "negative_tags": track.get("negative_tags"),
        "instrumental": bool(track.get("instrumental")),
        "creative_rationale": track.get("creative_rationale") or "",
    }

    soundcloud = _soundcloud_client(settings)
    result = distribution.publish(
        soundcloud, track["audio_path"], song, artist, private=private, artwork_path=track["cover_art_path"]
    )
    soundcloud_url = result.get("permalink_url")
    db.update_track(
        settings.db_path,
        track_id,
        soundcloud_track_id=str(result.get("id", "")),
        soundcloud_url=soundcloud_url,
        status="published",
    )
    return soundcloud_url


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

    trend_brief = db.get_cached_trend_brief(settings.db_path, settings.trend_cache_hours)
    if trend_brief:
        log.info("Using cached trend research (< %sh old)", settings.trend_cache_hours)
    else:
        log.info("Researching current music trends...")
        trend_brief = trend_research.run(claude, settings.claude_model)
        db.save_trend_brief(settings.db_path, trend_brief)

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
            creative_rationale=song.get("creative_rationale"),
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
    image_client = GeminiImageClient(settings.gemini_api_key or "", model=settings.gemini_image_model)
    cover_art_path = cover_art.generate(image_client, artist, song, settings.tracks_dir, track_id)
    db.update_track(settings.db_path, track_id, cover_art_path=cover_art_path)
    log.info("Cover art saved to %s", cover_art_path)

    soundcloud_url = None
    if publish:
        log.info("Publishing to SoundCloud...")
        soundcloud_url = publish_track(settings, track_id, private=private)
        log.info("Published: %s", soundcloud_url)

    return RunResult(
        track_id=track_id,
        title=song["title"],
        audio_path=audio_path,
        cover_art_path=cover_art_path,
        soundcloud_url=soundcloud_url,
    )
