"""Client for a Suno music-generation API.

There is no official public Suno API as of this writing — Suno announced an
API partner program in July 2026 but it is invite-only. In the meantime this
targets the request/response shape shared by the common third-party wrappers
(sunoapi.org, kie.ai, apibox.erweima.ai, and similar "Suno API" resellers),
which all converge on:

    POST {base_url}/api/v1/generate            -> {"data": {"taskId": "..."}}
    GET  {base_url}/api/v1/generate/record-info -> polling for completion

If your provider's field names differ, this is the one file to adjust —
everything else in the pipeline only talks to `SunoClient`.
"""

import time
from dataclasses import dataclass
from typing import Any

import httpx


class SunoError(RuntimeError):
    pass


@dataclass
class SunoTrack:
    audio_url: str
    title: str
    duration_seconds: float | None = None


class SunoClient:
    def __init__(self, base_url: str, api_key: str, model: str = "V4_5", timeout: float = 30.0):
        if not api_key:
            raise SunoError("SUNO_API_KEY is not set — see .env.example")
        self.base_url = base_url.rstrip("/")
        self.model = model
        self._client = httpx.Client(
            base_url=self.base_url,
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=timeout,
        )

    def generate(
        self,
        title: str,
        style: str,
        lyrics: str | None,
        instrumental: bool = False,
        negative_tags: str | None = None,
    ) -> str:
        """Submit a generation job. Returns the provider's task id."""
        payload: dict[str, Any] = {
            "customMode": True,
            "instrumental": instrumental,
            "title": title,
            "style": style,
            "model": self.model,
        }
        if not instrumental:
            payload["prompt"] = lyrics or ""
        if negative_tags:
            payload["negativeTags"] = negative_tags

        resp = self._client.post("/api/v1/generate", json=payload)
        resp.raise_for_status()
        body = resp.json()
        task_id = _dig(body, "data", "taskId")
        if not task_id:
            raise SunoError(f"Unexpected generate response shape: {body}")
        return task_id

    def wait_for_completion(
        self, task_id: str, poll_seconds: float = 10.0, timeout_seconds: float = 600.0
    ) -> list[SunoTrack]:
        """Poll until the job finishes, returning the generated track(s)."""
        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            resp = self._client.get("/api/v1/generate/record-info", params={"taskId": task_id})
            resp.raise_for_status()
            body = resp.json()
            status = (_dig(body, "data", "status") or "").upper()

            if status in {"SUCCESS", "COMPLETE", "COMPLETED", "FIRST_SUCCESS"}:
                items = (
                    _dig(body, "data", "response", "sunoData")
                    or _dig(body, "data", "response", "data")
                    or []
                )
                tracks = [
                    SunoTrack(
                        audio_url=item.get("audio_url") or item.get("audioUrl"),
                        title=item.get("title", ""),
                        duration_seconds=item.get("duration"),
                    )
                    for item in items
                    if item.get("audio_url") or item.get("audioUrl")
                ]
                if tracks:
                    return tracks
                # SUCCESS with no audio yet on some providers' "first" callback stage — keep polling.
            elif status in {"FAILED", "ERROR", "CREATE_TASK_FAILED", "GENERATE_AUDIO_FAILED"}:
                raise SunoError(f"Suno generation failed: {body}")

            time.sleep(poll_seconds)

        raise SunoError(f"Timed out waiting for Suno task {task_id}")

    def download(self, track: SunoTrack, destination: str) -> str:
        with httpx.stream("GET", track.audio_url, timeout=120.0) as resp:
            resp.raise_for_status()
            with open(destination, "wb") as fh:
                for chunk in resp.iter_bytes():
                    fh.write(chunk)
        return destination


def _dig(obj: dict[str, Any], *keys: str) -> Any:
    current: Any = obj
    for key in keys:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current
