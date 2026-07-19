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
app.add_typer(soundcloud_app, name="soundcloud")


@app.callback()
def main(verbose: bool = typer.Option(False, "--verbose", "-v")):
    logging.basicConfig(level=logging.INFO if verbose else logging.WARNING, format="%(message)s")
    logging.getLogger("vibemusicians").setLevel(logging.INFO)


@app.command()
def run(
    publish: bool = typer.Option(True, help="Upload the finished track to SoundCloud"),
    private: bool = typer.Option(True, help="Upload as private (recommended until you've reviewed the output)"),
):
    """Run the full pipeline once: research trends, write a song, generate audio, publish."""
    from vibemusicians.orchestrator import run_pipeline

    settings = get_settings()
    result = run_pipeline(settings, publish=publish, private=private)
    typer.echo(f"\nDone: track #{result.track_id} — {result.title!r}")
    typer.echo(f"Audio: {result.audio_path}")
    if result.soundcloud_url:
        typer.echo(f"SoundCloud: {result.soundcloud_url}")


@app.command()
def persona():
    """Show the current virtual artist persona (created on first `run`)."""
    from vibemusicians import db

    settings = get_settings()
    existing = db.load_persona(settings.db_path)
    if not existing:
        typer.echo("No persona yet — run `vibemusicians run` first.")
        raise typer.Exit(1)
    for key, value in existing.items():
        typer.echo(f"{key}: {value}")


@app.command()
def tracks(limit: int = 20):
    """List generated tracks."""
    from vibemusicians import db

    settings = get_settings()
    for track in db.list_tracks(settings.db_path, limit=limit):
        url = track.get("soundcloud_url") or "(not published)"
        typer.echo(f"#{track['id']:>4}  [{track['status']:<10}]  {track['title']:<40}  {url}")


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
