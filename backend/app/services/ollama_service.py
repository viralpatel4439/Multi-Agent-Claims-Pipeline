"""
Ollama vision client.
Sends image bytes + prompt to a running Ollama server and returns the raw text response.
Configure via OLLAMA_URL and OLLAMA_VISION_MODEL env vars.
"""
import base64
from typing import Optional

import httpx

from app.config import get_settings


async def extract_from_image_bytes(
    image_bytes: bytes,
    prompt: str,
    *,
    model: Optional[str] = None,
) -> str:
    """
    Send image bytes to Ollama vision model and return the raw text response.

    Args:
        image_bytes: Raw bytes of a PNG/JPEG image.
        prompt: Extraction instruction sent alongside the image.
        model: Override the default vision model from settings.

    Returns:
        Raw text from the model (caller is responsible for JSON parsing).

    Raises:
        httpx.HTTPStatusError: On non-2xx responses from Ollama.
        httpx.ConnectError: If Ollama is not reachable at the configured URL.
    """
    settings = get_settings()
    b64 = base64.b64encode(image_bytes).decode()

    payload = {
        "model": model or settings.ollama_vision_model,
        "messages": [
            {
                "role": "user",
                "content": prompt,
                "images": [b64],
            }
        ],
        "stream": False,
    }

    async with httpx.AsyncClient(timeout=120.0) as client:
        resp = await client.post(
            f"{settings.ollama_url}/api/chat",
            json=payload,
        )
        resp.raise_for_status()
        return resp.json()["message"]["content"]
