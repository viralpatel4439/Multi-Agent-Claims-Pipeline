"""
Ollama vision client.
Sends image bytes + prompt to a running Ollama server and returns the raw text response.
Configure via OLLAMA_URL and OLLAMA_VISION_MODEL env vars.
"""
import base64
import logging
from typing import Optional

import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)


async def _post(url: str, payload: dict) -> dict:
    total_b64 = sum(len(img) for img in payload["messages"][0].get("images", []))
    logger.info("[Ollama] POST %s  model=%s  images=%d  total_b64_bytes=%d",
                url, payload["model"], len(payload["messages"][0].get("images", [])), total_b64)

    async with httpx.AsyncClient(timeout=600.0) as client:
        resp = await client.post(url, json=payload)

    logger.info("[Ollama] status=%d  body=%s", resp.status_code, resp.text[:500])

    if not resp.is_success:
        raise RuntimeError(f"Ollama {resp.status_code}: {resp.text[:300]}")

    return resp.json()


async def extract_from_image_bytes(
    image_bytes: bytes,
    prompt: str,
    *,
    model: Optional[str] = None,
) -> str:
    """Single image extraction."""
    return await extract_from_image_batch([image_bytes], prompt, model=model)


async def extract_from_image_batch(
    images: list[bytes],
    prompt: str,
    *,
    model: Optional[str] = None,
) -> str:
    """
    Send multiple images in a single Ollama call.
    All images go into one message — one API round-trip regardless of document count.
    Returns the raw text content from the model.
    """
    settings = get_settings()
    model_name = model or settings.ollama_vision_model
    url = f"{settings.ollama_url}/api/chat"

    b64_images = [base64.b64encode(img).decode() for img in images]

    payload = {
        "model": model_name,
        "messages": [
            {
                "role": "user",
                "content": prompt,
                "images": b64_images,
            }
        ],
        "stream": False,
        "options": {"num_ctx": 32768},
    }

    result = await _post(url, payload)
    return result["message"]["content"]
