"""Read-modify-write helper for .env files.

Used to persist values a running process discovers it needs to remember for
next time — e.g. SoundCloud's rotating refresh token — back into .env, since
pydantic-settings only reads .env at startup.
"""

from pathlib import Path


def upsert(key: str, value: str, env_path: Path = Path(".env")) -> None:
    lines = env_path.read_text().splitlines() if env_path.exists() else []
    for i, line in enumerate(lines):
        if line.startswith(f"{key}="):
            lines[i] = f"{key}={value}"
            break
    else:
        lines.append(f"{key}={value}")
    env_path.write_text("\n".join(lines) + "\n")
