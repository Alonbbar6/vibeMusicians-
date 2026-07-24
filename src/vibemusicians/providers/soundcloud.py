"""SoundCloud API client: OAuth 2.1 + PKCE login and track upload.

SoundCloud is the only distribution target for v1. Apple Music (and Spotify)
have no public API for individual artists to upload directly — real releases
there go through a distributor (DistroKid, TuneCore, CD Baby, ...). This
client is written so a second `DistributionProvider` can be added later
without touching the pipeline — see agents/distribution.py.
"""

import base64
import hashlib
import mimetypes
import secrets
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

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

    def __init__(
        self,
        client_id: str,
        client_secret: str,
        refresh_token: str,
        on_token_rotated: Callable[[str], None] | None = None,
    ):
        if not (client_id and client_secret and refresh_token):
            raise SoundCloudError(
                "SoundCloud is not configured — run `vibemusicians soundcloud login` first"
            )
        self.client_id = client_id
        self.client_secret = client_secret
        self.refresh_token = refresh_token
        self.on_token_rotated = on_token_rotated
        self._access_token: str | None = None
        # Unix time (seconds) after which the cached access token is considered
        # expired. 0 means "no valid token yet".
        self._access_expires_at: float = 0.0

    def _access(self) -> str:
        # Access tokens are valid for ~1 hour, so reuse the one we already have
        # until it's close to expiring. Only then do we spend a single-use
        # refresh token to mint a new one. This is the key reliability fix:
        # the old code refreshed on EVERY API call, which rotated (and
        # invalidated) the refresh token several times per run and multiplied
        # the chance of a lost update leaving the stored token dead. Now a
        # whole run normally spends exactly one refresh token.
        if self._access_token and time.time() < self._access_expires_at:
            return self._access_token
        return self._refresh()

    def _refresh(self) -> str:
        # The refresh token is single-use — SoundCloud invalidates it the
        # instant the server processes the request, so only ConnectError
        # (DNS/connection failure, meaning no bytes ever reached the server)
        # is safe to retry. Any error past that point is ambiguous about
        # whether the token was already consumed, so it's left to fail.
        for attempt in range(3):
            try:
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
                break
            except httpx.ConnectError:
                if attempt == 2:
                    raise
                time.sleep(2.0)
        resp.raise_for_status()
        body = resp.json()
        self._access_token = body["access_token"]
        # Cache how long this access token is good for (default to 1 hour if
        # SoundCloud omits expires_in), minus a 60s safety margin so we never
        # use one that expires mid-request.
        expires_in = int(body.get("expires_in", 3600))
        self._access_expires_at = time.time() + max(0, expires_in - 60)
        # SoundCloud rotates refresh tokens on every refresh and invalidates the
        # old one immediately, so the caller must persist this somewhere that
        # survives past this process, or every future run fails with a 400.
        new_refresh_token = body.get("refresh_token")
        if new_refresh_token and new_refresh_token != self.refresh_token:
            self.refresh_token = new_refresh_token
            if self.on_token_rotated:
                self.on_token_rotated(new_refresh_token)
        return self._access_token

    def get_current_user(self) -> dict[str, Any]:
        access_token = self._access()
        resp = httpx.get(
            f"{API_BASE}/me",
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=30.0,
        )
        if resp.status_code >= 400:
            raise SoundCloudError(f"SoundCloud get current user failed ({resp.status_code}): {resp.text}")
        return resp.json()

    def list_comments(self, track_id: str, limit: int = 50) -> list[dict[str, Any]]:
        access_token = self._access()
        resp = httpx.get(
            f"{API_BASE}/tracks/{track_id}/comments",
            headers={"Authorization": f"Bearer {access_token}"},
            params={"limit": limit, "linked_partitioning": "true"},
            timeout=30.0,
        )
        if resp.status_code >= 400:
            raise SoundCloudError(f"SoundCloud list comments failed ({resp.status_code}): {resp.text}")
        body = resp.json()
        # linked_partitioning wraps results in {"collection": [...], "next_href": ...}
        return body.get("collection", body) if isinstance(body, dict) else body

    def post_comment(self, track_id: str, body: str) -> dict[str, Any]:
        access_token = self._access()
        resp = httpx.post(
            f"{API_BASE}/tracks/{track_id}/comments",
            headers={"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"},
            json={"comment": {"body": body}},
            timeout=30.0,
        )
        if resp.status_code >= 400:
            raise SoundCloudError(f"SoundCloud post comment failed ({resp.status_code}): {resp.text}")
        return resp.json()

    def set_sharing(self, track_id: str, private: bool) -> dict[str, Any]:
        access_token = self._access()
        resp = httpx.put(
            f"{API_BASE}/tracks/{track_id}",
            headers={"Authorization": f"Bearer {access_token}"},
            data={"track[sharing]": "private" if private else "public"},
            timeout=30.0,
        )
        if resp.status_code >= 400:
            raise SoundCloudError(f"SoundCloud update failed ({resp.status_code}): {resp.text}")
        return resp.json()

    def upload_track(
        self,
        audio_path: str,
        title: str,
        description: str = "",
        tag_list: str = "",
        genre: str = "",
        private: bool = True,
        artwork_path: str | None = None,
    ) -> dict[str, Any]:
        access_token = self._access()
        with open(audio_path, "rb") as audio_file:
            files = {"track[asset_data]": (Path(audio_path).name, audio_file, "audio/mpeg")}
            artwork_file = open(artwork_path, "rb") if artwork_path else None
            try:
                if artwork_file:
                    content_type = mimetypes.guess_type(artwork_path)[0] or "image/png"
                    files["track[artwork_data]"] = (Path(artwork_path).name, artwork_file, content_type)
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
                    files=files,
                    timeout=300.0,
                )
            finally:
                if artwork_file:
                    artwork_file.close()
        if resp.status_code >= 400:
            raise SoundCloudError(f"SoundCloud upload failed ({resp.status_code}): {resp.text}")
        return resp.json()
