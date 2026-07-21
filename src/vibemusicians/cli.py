import http.server
import logging
import secrets
import threading
import webbrowser
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import typer

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
    private: bool = typer.Option(True, help="Upload as private (recommended until you've reviewed the output)"),
    artist: str = typer.Option(None, help="Name of an existing roster artist to write for"),
    new_artist: bool = typer.Option(False, "--new-artist", help="Invent and add a new artist to the roster"),
    direction: str = typer.Option(None, help="Creative direction hint, only used with --new-artist"),
):
    """Run the full pipeline once: research trends, write a song, generate audio, publish."""
    from vibemusicians.orchestrator import AmbiguousArtist, ArtistNotFound, UploadLimitReached, run_pipeline

    settings = get_settings()
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
    except (ArtistNotFound, AmbiguousArtist) as e:
        typer.echo(str(e))
        raise typer.Exit(1)
    typer.echo(f"\nDone: track #{result.track_id} — {result.title!r}")
    typer.echo(f"Audio: {result.audio_path}")
    typer.echo(f"Cover art: {result.cover_art_path}")
    if result.soundcloud_url:
        typer.echo(f"SoundCloud: {result.soundcloud_url}")


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


@artist_app.command("create")
def artist_create(direction: str = typer.Option(None, help="Creative direction hint, e.g. 'dark synthwave, male vocals'")):
    """Invent a new artist and add them to the label's roster."""
    import anthropic

    from vibemusicians import db
    from vibemusicians.agents import persona, trend_research

    settings = get_settings()
    claude = anthropic.Anthropic(api_key=settings.anthropic_api_key)

    typer.echo("Researching current music trends...")
    trend_brief = trend_research.run(claude, settings.claude_model)

    existing = db.list_artists(settings.db_path)
    typer.echo("Inventing artist...")
    invented = persona.invent(
        claude, settings.claude_model, trend_brief, direction=direction, existing_artists=existing
    )
    artist_id = db.create_artist(settings.db_path, invented)

    typer.echo(f"\nCreated artist #{artist_id}: {invented['name']} ({invented['genre']})")
    typer.echo(f"Tagline: {invented['tagline']}")
    typer.echo(f"Vocal style: {invented['vocal_style']}")


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
    _upsert_env_var("SOUNDCLOUD_REFRESH_TOKEN", refresh_token)
    typer.echo("Connected. SOUNDCLOUD_REFRESH_TOKEN saved to .env.")


def _upsert_env_var(key: str, value: str, env_path: Path = Path(".env")) -> None:
    lines = env_path.read_text().splitlines() if env_path.exists() else []
    for i, line in enumerate(lines):
        if line.startswith(f"{key}="):
            lines[i] = f"{key}={value}"
            break
    else:
        lines.append(f"{key}={value}")
    env_path.write_text("\n".join(lines) + "\n")


if __name__ == "__main__":
    app()
