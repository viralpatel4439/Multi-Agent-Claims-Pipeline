"""
NVIDIA NIM API client.
Usage:
    from app.services.nvidia_service import get_completion
    text = await get_completion("minimaxai/minimax-m3", "Summarise this claim...")
"""
import os
from typing import Optional

import httpx

NVIDIA_INVOKE_URL = "https://integrate.api.nvidia.com/v1/chat/completions"


async def get_completion(
    model: str,
    user_message: str,
    *,
    max_tokens: int = 8192,
    temperature: float = 1.0,
    top_p: float = 0.95,
    api_key: Optional[str] = None,
) -> str:
    """
    Call the NVIDIA NIM chat completions endpoint and return the response text.

    Args:
        model: NVIDIA model ID, e.g. "minimaxai/minimax-m3"
        user_message: The user prompt to send.
        max_tokens: Maximum tokens in the response.
        temperature: Sampling temperature.
        top_p: Nucleus sampling probability.
        api_key: Override the NVIDIA_API_KEY env var for this call.

    Returns:
        The assistant's reply as a plain string.

    Raises:
        ValueError: If no API key is available.
        httpx.HTTPStatusError: On non-2xx responses.
    """
    key = api_key or os.environ.get("NVIDIA_API_KEY", "")
    if not key:
        raise ValueError("NVIDIA_API_KEY is not set. Add it to your .env file.")

    headers = {
        "Authorization": f"Bearer {key}",
        "Accept": "application/json",
    }
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": user_message}],
        "max_tokens": max_tokens,
        "temperature": temperature,
        "top_p": top_p,
        "stream": False,
    }

    async with httpx.AsyncClient(timeout=60.0) as client:
        response = await client.post(NVIDIA_INVOKE_URL, headers=headers, json=payload)
        response.raise_for_status()
        data = response.json()
        return data["choices"][0]["message"]["content"]
