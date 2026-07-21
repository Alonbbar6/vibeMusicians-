import http.server
import logging
import secrets
import threading
import webbrowser
from urllib.parse import parse_qs, urlparse

import typer

from vibemusicians import env_file
from vibemusicians.config import get_settings
from vibemusicians.providers import soundcloud as sc

app = typer.Typer(help="Autonomous music-agent pipeline: research -> persona -> song -> Suno -> SoundCloud")
soundcloud_app = typer.Typer(help="SoundCloud account connection")
artist_app = typer.Typer(help="Manage the label's artist roster")
app.add_typer(soundcloud_app, name="soundcloud")
app.add_typer(artist_app, name="artist")


@app.callback()
def main(verbose: bool = typer.Option(False, "--verbose", "-v")):
    logging.basicConfig(level=logging.INFO if verbose else logging.WARNING, format="%(message)s")
    logging.getLogger("vibemusicians").setLevel(logging.INFO)


@app.command()
def run(
    publish: bool = typer.Option(True, help="Upload the finished track to SoundCloud"),
    private: bool = typer.Option(False, help="Upload as private instead of public"),
    artist: str = typer.Option(None, help="Name of an existing roster artist to write for"),
    new_artist: bool = typer.Option(False, "--new-artist", help="Invent and add a new artist to the roster"),
    direction: str = typer.Option(None, help="Creative direction hint, only used with --new-artist"),
    count: int = typer.Option(
        1, help="How many songs to generate this invocation. >1 round-robins across the roster unless --artist is set"
    ),
):
    """Run the full pipeline once (or --count times): research trends, write a song, generate audio, publish."""
    from vibemusicians import db
    from vibemusicians.orchestrator import (
        AmbiguousArtist,
        ArtistNotFound,
        RosterFull,
        UploadLimitReached,
        run_pipeline,
    )

    settings = get_settings()

    if count == 1:
        try:
            result = run_pipeline(
                settings,
                publish=publish,
                private=private,
                artist_name=artist,
                new_artist=new_artist,
                direction=direction,
            )
        except UploadLimitReached as e:
            typer.echo(str(e))
            raise typer.Exit(0)
        except (ArtistNotFound, AmbiguousArtist, RosterFull) as e:
            typer.echo(str(e))
            raise typer.Exit(1)
        typer.echo(f"\nDone: track #{result.track_id} — {result.title!r}")
        typer.echo(f"Audio: {result.audio_path}")
        typer.echo(f"Cover art: {result.cover_art_path}")
        if result.soundcloud_url:
            typer.echo(f"SoundCloud: {result.soundcloud_url}")
        return

    if new_artist:
        typer.echo("--new-artist can't be combined with --count > 1. Add the artist first, then rerun with --count.")
        raise typer.Exit(1)
    roster = db.list_artists(settings.db_path)
    if not artist and not roster:
        typer.echo("No artists yet — run `vibemusicians artist create` first.")
        raise typer.Exit(1)

    for i in range(count):
        pick = artist or roster[i % len(roster)]["name"]
        try:
            result = run_pipeline(settings, publish=publish, private=private, artist_name=pick)
            link = f" -> {result.soundcloud_url}" if result.soundcloud_url else ""
            typer.echo(f"[{i + 1}/{count}] {pick}: #{result.track_id} {result.title!r}{link}")
        except UploadLimitReached as e:
            typer.echo(f"[{i + 1}/{count}] {pick}: skipped — {e}")
        except (ArtistNotFound, AmbiguousArtist, RosterFull) as e:
            typer.echo(f"[{i + 1}/{count}] {pick}: error — {e}")


@app.command()
def tracks(artist: str = typer.Option(None, help="Only show tracks for this artist"), limit: int = 20):
    """List generated tracks."""
    from vibemusicians import db

    settings = get_settings()
    artist_id = None
    if artist:
        match = db.get_artist_by_name(settings.db_path, artist)
        if not match:
            typer.echo(f"No artist named {artist!r}.")
            raise typer.Exit(1)
        artist_id = match["id"]

    for track in db.list_tracks(settings.db_path, artist_id=artist_id, limit=limit):
        url = track.get("soundcloud_url") or "(not published)"
        artist_label = track.get("artist_name") or "?"
        typer.echo(f"#{track['id']:>4}  [{track['status']:<10}]  {artist_label:<20}  {track['title']:<40}  {url}")


@app.command()
def make_public(track_id: int):
    """Flip an already-published track from private to public on SoundCloud."""
    from vibemusicians.orchestrator import TrackNotReady, set_track_sharing

    settings = get_settings()
    try:
        set_track_sharing(settings, track_id, private=False)
    except TrackNotReady as e:
        typer.echo(str(e))
        raise typer.Exit(1)
    typer.echo(f"Track #{track_id} is now public.")


@artist_app.command("create")
def artist_create(direction: str = typer.Option(None, help="Creative direction hint, e.g. 'dark synthwave, male vocals'")):
    """Invent a new artist and add them to the label's roster."""
    import anthropic

    from vibemusicians import db
    from vibemusicians.agents import persona, trend_research

    settings = get_settings()
    existing = db.list_artists(settings.db_path)
    if len(existing) >= settings.max_artists:
        typer.echo(
            f"Roster is full ({len(existing)}/{settings.max_artists} artists). "
            "Adjust MAX_ARTISTS in .env to allow more."
        )
        raise typer.Exit(1)

    claude = anthropic.Anthropic(api_key=settings.anthropic_api_key)

    typer.echo("Researching current music trends...")
    trend_brief = trend_research.run(claude, settings.claude_model)

    typer.echo("Inventing artist...")
    invented = persona.invent(
        claude, settings.claude_model, trend_brief, direction=direction, existing_artists=existing
    )
    artist_id = db.create_artist(settings.db_path, invented)

    typer.echo(f"\nCreated artist #{artist_id}: {invented['name']} ({invented['genre']})")
    typer.echo(f"Tagline: {invented['tagline']}")
    typer.echo(f"Vocal style: {invented['vocal_style']}")


@artist_app.command("ensure")
def artist_ensure(direction: str = typer.Option(None, help="Creative direction hint if an artist needs to be created")):
    """Create the first artist only if the roster is currently empty; no-op otherwise.

    Useful as a bootstrap step before `run --count N` in CI, where a fresh
    checkout has no roster yet.
    """
    from vibemusicians import db

    settings = get_settings()
    if db.list_artists(settings.db_path):
        typer.echo("Roster already has artist(s) — nothing to do.")
        return
    artist_create(direction=direction)


@artist_app.command("list")
def artist_list():
    """List every artist on the roster."""
    from vibemusicians import db

    settings = get_settings()
    artists = db.list_artists(settings.db_path)
    if not artists:
        typer.echo("No artists yet — run `vibemusicians artist create` or `vibemusicians run`.")
        raise typer.Exit(0)
    for a in artists:
        track_count = len(db.list_tracks(settings.db_path, artist_id=a["id"], limit=1000))
        typer.echo(f"#{a['id']} {a['name']} ({a['genre']}) — {track_count} track(s)")
        typer.echo(f"    Vocal style: {a['vocal_style']}")


@artist_app.command("show")
def artist_show(name: str):
    """Show full bio for one artist."""
    from vibemusicians import db

    settings = get_settings()
    a = db.get_artist_by_name(settings.db_path, name)
    if not a:
        typer.echo(f"No artist named {name!r}.")
        raise typer.Exit(1)
    for key, value in a.items():
        typer.echo(f"{key}: {value}")


@app.command()
def dashboard(
    port: int = typer.Option(8913, help="Port to serve the dashboard on"),
    no_browser: bool = typer.Option(False, "--no-browser", help="Don't auto-open a browser tab"),
):
    """Launch a local web dashboard: artist bio, connected accounts, songs, pipeline status."""
    from vibemusicians.dashboard import run_dashboard

    settings = get_settings()
    run_dashboard(settings, port=port, open_browser=not no_browser)


@soundcloud_app.command("login")
def soundcloud_login():
    """One-time interactive OAuth (PKCE) flow to connect a SoundCloud account."""
    settings = get_settings()
    if not (settings.soundcloud_client_id and settings.soundcloud_client_secret):
        typer.echo("Set SOUNDCLOUD_CLIENT_ID and SOUNDCLOUD_CLIENT_SECRET in .env first.")
        raise typer.Exit(1)

    redirect = urlparse(settings.soundcloud_redirect_uri)
    host, port = redirect.hostname or "localhost", redirect.port or 80

    challenge = sc.make_pkce_challenge()
    state = secrets.token_urlsafe(16)
    authorize_url = sc.build_authorize_url(
        settings.soundcloud_client_id, settings.soundcloud_redirect_uri, state, challenge.challenge
    )

    result: dict[str, str] = {}

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            query = parse_qs(urlparse(self.path).query)
            result["code"] = query.get("code", [""])[0]
            result["state"] = query.get("state", [""])[0]
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(b"<html><body>Connected. You can close this tab.</body></html>")

        def log_message(self, *args):  # silence default request logging
            pass

    server = http.server.HTTPServer((host, port), Handler)
    thread = threading.Thread(target=server.handle_request, daemon=True)
    thread.start()

    typer.echo(f"Opening browser to authorize SoundCloud access:\n{authorize_url}\n")
    webbrowser.open(authorize_url)
    thread.join(timeout=180)

    if not result.get("code"):
        typer.echo("Timed out waiting for the SoundCloud redirect.")
        raise typer.Exit(1)
    if result.get("state") != state:
        typer.echo("State mismatch — aborting for safety.")
        raise typer.Exit(1)

    tokens = sc.exchange_code_for_token(
        settings.soundcloud_client_id,
        settings.soundcloud_client_secret,
        settings.soundcloud_redirect_uri,
        result["code"],
        challenge.verifier,
    )
    refresh_token = tokens["refresh_token"]
    env_file.upsert("SOUNDCLOUD_REFRESH_TOKEN", refresh_token)
    typer.echo("Connected. SOUNDCLOUD_REFRESH_TOKEN saved to .env.")


if __name__ == "__main__":
    app()
