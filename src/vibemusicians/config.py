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

    # SoundCloud
    soundcloud_client_id: str | None = None
    soundcloud_client_secret: str | None = None
    soundcloud_redirect_uri: str = "http://localhost:8912/callback"
    soundcloud_refresh_token: str | None = None

    # Rate limiting: max tracks published to SoundCloud per rolling 7-day
    # window, per artist. Adjust via WEEKLY_UPLOAD_LIMIT in .env.
    weekly_upload_limit: int = 3

    # Local storage
    data_dir: Path = Path("data")

    @property
    def db_path(self) -> Path:
        return self.data_dir / "vibemusicians.db"

    @property
    def tracks_dir(self) -> Path:
        return self.data_dir / "tracks"


def get_settings() -> Settings:
    settings = Settings()
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    settings.tracks_dir.mkdir(parents=True, exist_ok=True)
    return settings
