"""SoundCloud API client: OAuth 2.1 + PKCE login and track upload.

SoundCloud is the only distribution target for v1. Apple Music (and Spotify)
have no public API for individual artists to upload directly — real releases
there go through a distributor (DistroKid, TuneCore, CD Baby, ...). This
client is written so a second `DistributionProvider` can be added later
without touching the pipeline — see agents/distribution.py.
"""

import base64
import hashlib
import secrets
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

AUTHORIZE_URL = "https://secure.soundcloud.com/authorize"
TOKEN_URL = "https://secure.soundcloud.com/oauth/token"
API_BASE = "https://api.soundcloud.com"


class SoundCloudError(RuntimeError):
    pass


@dataclass
class PKCEChallenge:
    verifier: str
    challenge: str


def make_pkce_challenge() -> PKCEChallenge:
    verifier = base64.urlsafe_b64encode(secrets.token_bytes(40)).rstrip(b"=").decode()
    digest = hashlib.sha256(verifier.encode()).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
    return PKCEChallenge(verifier=verifier, challenge=challenge)


def build_authorize_url(client_id: str, redirect_uri: str, state: str, challenge: str) -> str:
    params = httpx.QueryParams(
        {
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "state": state,
        }
    )
    return f"{AUTHORIZE_URL}?{params}"


def exchange_code_for_token(
    client_id: str,
    client_secret: str,
    redirect_uri: str,
    code: str,
    code_verifier: str,
) -> dict[str, Any]:
    resp = httpx.post(
        TOKEN_URL,
        data={
            "grant_type": "authorization_code",
            "client_id": client_id,
            "client_secret": client_secret,
            "redirect_uri": redirect_uri,
            "code": code,
            "code_verifier": code_verifier,
        },
        headers={"accept": "application/json"},
        timeout=30.0,
    )
    resp.raise_for_status()
    return resp.json()


class SoundCloudClient:
    """Uses a stored refresh token to mint access tokens and upload tracks."""

    def __init__(self, client_id: str, client_secret: str, refresh_token: str):
        if not (client_id and client_secret and refresh_token):
            raise SoundCloudError(
                "SoundCloud is not configured — run `vibemusicians soundcloud login` first"
            )
        self.client_id = client_id
        self.client_secret = client_secret
        self.refresh_token = refresh_token
        self._access_token: str | None = None

    def _refresh(self) -> str:
        resp = httpx.post(
            TOKEN_URL,
            data={
                "grant_type": "refresh_token",
                "client_id": self.client_id,
                "client_secret": self.client_secret,
                "refresh_token": self.refresh_token,
            },
            headers={"accept": "application/json"},
            timeout=30.0,
        )
        resp.raise_for_status()
        body = resp.json()
        self._access_token = body["access_token"]
        # SoundCloud rotates refresh tokens on every refresh — persist the new one.
        if body.get("refresh_token"):
            self.refresh_token = body["refresh_token"]
        return self._access_token

    def upload_track(
        self,
        audio_path: str,
        title: str,
        description: str = "",
        tag_list: str = "",
        genre: str = "",
        private: bool = True,
    ) -> dict[str, Any]:
        access_token = self._refresh()
        with open(audio_path, "rb") as audio_file:
            resp = httpx.post(
                f"{API_BASE}/tracks",
                headers={"Authorization": f"Bearer {access_token}"},
                data={
                    "track[title]": title,
                    "track[description]": description,
                    "track[tag_list]": tag_list,
                    "track[genre]": genre,
                    "track[sharing]": "private" if private else "public",
                },
                files={"track[asset_data]": (Path(audio_path).name, audio_file, "audio/mpeg")},
                timeout=300.0,
            )
        if resp.status_code >= 400:
            raise SoundCloudError(f"SoundCloud upload failed ({resp.status_code}): {resp.text}")
        return resp.json()
