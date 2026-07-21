"""Client for kie.ai's GPT-Image-1 ("4o Image") generation API.

Same account/API key as SunoClient — both are kie.ai endpoints. See
https://docs.kie.ai/4o-image-api for the request/response shapes this
targets: POST /api/v1/gpt4o-image/generate to submit, GET
/api/v1/gpt4o-image/record-info to poll.
"""

import time
from dataclasses import dataclass
from typing import Any

import httpx


class ImageError(RuntimeError):
    pass


@dataclass
class GeneratedImage:
    url: str


class ImageClient:
    def __init__(
        self,
        base_url: str,
        api_key: str,
        callback_url: str = "https://example.com/vibemusicians-callback",
        timeout: float = 30.0,
    ):
        if not api_key:
            raise ImageError("SUNO_API_KEY is not set — the image client reuses the kie.ai key")
        self.base_url = base_url.rstrip("/")
        self.callback_url = callback_url
        self._client = httpx.Client(
            base_url=self.base_url,
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=timeout,
        )

    def generate(self, prompt: str, size: str = "1:1") -> str:
        """Submit an image generation job. Returns the provider's task id."""
        resp = self._client.post(
            "/api/v1/gpt4o-image/generate",
            json={"prompt": prompt, "size": size, "callBackUrl": self.callback_url},
        )
        resp.raise_for_status()
        body = resp.json()
        task_id = _dig(body, "data", "taskId")
        if not task_id:
            raise ImageError(f"Unexpected generate response shape: {body}")
        return task_id

    def wait_for_completion(
        self, task_id: str, poll_seconds: float = 10.0, timeout_seconds: float = 600.0
    ) -> list[GeneratedImage]:
        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            resp = self._client.get("/api/v1/gpt4o-image/record-info", params={"taskId": task_id})
            resp.raise_for_status()
            body = resp.json()
            status = (_dig(body, "data", "status") or "").upper()

            if status == "SUCCESS":
                urls = _dig(body, "data", "response", "resultUrls") or []
                images = [GeneratedImage(url=u) for u in urls if u]
                if images:
                    return images
            elif "ERROR" in status or "FAILED" in status:
                error_message = _dig(body, "data", "errorMessage") or body
                raise ImageError(f"Image generation failed ({status}): {error_message}")

            time.sleep(poll_seconds)

        raise ImageError(f"Timed out waiting for image task {task_id}")

    def download(self, image: GeneratedImage, destination: str) -> str:
        with httpx.stream("GET", image.url, timeout=60.0) as resp:
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
