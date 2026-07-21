"""Client for Google's Gemini native image generation.

Unlike kie.ai's image endpoint, this is synchronous — one request returns the
finished image directly (no task id / polling), which is what actually fixes
the timeout flakiness seen generating cover art from GitHub Actions runners,
rather than just giving it a longer deadline.

See https://ai.google.dev/gemini-api/docs/image-generation — POST
/v1beta/models/{model}:generateContent with generationConfig.responseModalities
including "IMAGE"; the image comes back base64-encoded in
candidates[0].content.parts[].inlineData.
"""

import base64
from dataclasses import dataclass

import httpx


class GeminiImageError(RuntimeError):
    pass


@dataclass
class GeneratedImage:
    data: bytes
    mime_type: str


class GeminiImageClient:
    def __init__(self, api_key: str, model: str = "gemini-2.5-flash-image", timeout: float = 120.0):
        if not api_key:
            raise GeminiImageError("GEMINI_API_KEY is not set — see .env.example")
        self.model = model
        self._client = httpx.Client(
            base_url="https://generativelanguage.googleapis.com",
            headers={"x-goog-api-key": api_key},
            timeout=timeout,
        )

    def generate(self, prompt: str) -> GeneratedImage:
        resp = self._client.post(
            f"/v1beta/models/{self.model}:generateContent",
            json={
                "contents": [{"parts": [{"text": prompt}]}],
                "generationConfig": {"responseModalities": ["IMAGE"]},
            },
        )
        resp.raise_for_status()
        body = resp.json()
        candidates = body.get("candidates") or []
        parts = candidates[0].get("content", {}).get("parts", []) if candidates else []
        for part in parts:
            inline = part.get("inlineData")
            if inline and inline.get("data"):
                return GeneratedImage(
                    data=base64.b64decode(inline["data"]),
                    mime_type=inline.get("mimeType", "image/png"),
                )
        raise GeminiImageError(f"No image returned: {body}")

    def download(self, image: GeneratedImage, destination: str) -> str:
        with open(destination, "wb") as fh:
            fh.write(image.data)
        return destination
