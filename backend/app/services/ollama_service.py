"""
Ollama vision client with timeout and exponential-backoff retry.
Configure via OLLAMA_URL and OLLAMA_VISION_MODEL env vars.
"""
import asyncio
import base64
import logging
from typing import Optional

import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)

# Per-request limits: 10s to connect, 180s to receive the full response.
# Vision inference on a 3B model typically finishes in 30–90s.
_TIMEOUT = httpx.Timeout(connect=10.0, read=180.0, write=30.0, pool=5.0)
_MAX_ATTEMPTS = 3
_RETRY_BASE_S = 5  # 5s → 15s → 45s


async def _post(url: str, payload: dict) -> dict:
    images = payload["messages"][0].get("images", [])
    logger.info(
        "[Ollama] POST %s  model=%s  images=%d  total_b64_bytes=%d",
        url, payload["model"], len(images), sum(len(i) for i in images),
    )

    last_exc: Exception = RuntimeError("No attempts made")
    for attempt in range(_MAX_ATTEMPTS):
        try:
            async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
                resp = await client.post(url, json=payload)

            logger.info("[Ollama] status=%d  body=%s", resp.status_code, resp.text[:500])

            if resp.is_success:
                return resp.json()

            # 5xx errors are transient — retry; 4xx are caller bugs — don't retry
            if resp.status_code < 500:
                raise RuntimeError(f"Ollama {resp.status_code}: {resp.text[:300]}")

            last_exc = RuntimeError(f"Ollama {resp.status_code}: {resp.text[:300]}")

        except (httpx.TimeoutException, httpx.ConnectError, httpx.RemoteProtocolError) as exc:
            last_exc = exc
            logger.warning(
                "[Ollama] attempt %d/%d failed (%s: %s)",
                attempt + 1, _MAX_ATTEMPTS, type(exc).__name__, exc,
            )

        if attempt < _MAX_ATTEMPTS - 1:
            delay = _RETRY_BASE_S * (3 ** attempt)  # 5s, 15s, 45s
            logger.info("[Ollama] retrying in %ds…", delay)
            await asyncio.sleep(delay)

    raise RuntimeError(f"Ollama failed after {_MAX_ATTEMPTS} attempts: {last_exc}") from last_exc


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
