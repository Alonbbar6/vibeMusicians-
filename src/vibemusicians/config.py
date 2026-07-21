from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Anthropic
    anthropic_api_key: str | None = None
    claude_model: str = "claude-opus-4-8"

    # Suno (third-party wrapper — see .env.example)
    suno_api_base_url: str = "https://api.kie.ai"
    suno_api_key: str | None = None
    suno_model: str = "V4_5"
    # kie.ai requires a callBackUrl on every generate call, but this app polls
    # for results instead of receiving callbacks, so it never needs to be a
    # real reachable endpoint — see providers/suno.py.
    suno_callback_url: str = "https://example.com/vibemusicians-callback"

    # Gemini (cover art — separate provider from Suno, synchronous, no polling)
    gemini_api_key: str | None = None
    gemini_image_model: str = "gemini-2.5-flash-image"

    # SoundCloud
    soundcloud_client_id: str | None = None
    soundcloud_client_secret: str | None = None
    soundcloud_redirect_uri: str = "http://localhost:8912/callback"
    soundcloud_refresh_token: str | None = None

    # Rate limiting: max tracks published to SoundCloud per rolling 7-day
    # window, per artist. Adjust via WEEKLY_UPLOAD_LIMIT in .env.
    weekly_upload_limit: int = 3

    # Roster cap: max number of artists the label can have at once. Adjust via
    # MAX_ARTISTS in .env.
    max_artists: int = 3

    # How long a cached trend research brief stays valid before a fresh (paid,
    # multi-round web-search) research call is made again. Trends don't shift
    # meaningfully hour to hour, so reusing one avoids re-researching for
    # every song. Adjust via TREND_CACHE_HOURS in .env.
    trend_cache_hours: int = 24

    # Local storage
    data_dir: Path = Path("data")

    @property
    def db_path(self) -> Path:
        return self.data_dir / "vibemusicians.db"

    @property
    def tracks_dir(self) -> Path:
        return self.data_dir / "tracks"

    @property
    def soundcloud_token_path(self) -> Path:
        return self.data_dir / "soundcloud_refresh_token"


def get_settings() -> Settings:
    settings = Settings()
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    settings.tracks_dir.mkdir(parents=True, exist_ok=True)

    # SoundCloud rotates this token on every use and invalidates the old one,
    # so whatever a prior run last wrote here is more current than the
    # SOUNDCLOUD_REFRESH_TOKEN env var / .env value — this file is what
    # actually survives across separate CI job runs (each a fresh container,
    # no .env), committed alongside data/vibemusicians.db.
    if settings.soundcloud_token_path.exists():
        settings.soundcloud_refresh_token = settings.soundcloud_token_path.read_text().strip()

    return settings
