"""
Debug endpoint — fires the exact same Ollama /api/chat call the extractor uses.
Hit POST /api/debug/ollama-test with a form-file to test vision extraction,
or without a file to use a built-in 1×1 white PNG.
"""
import base64
import struct
import zlib
from typing import Optional

import httpx
from fastapi import APIRouter, UploadFile
from app.config import get_settings

router = APIRouter()


def _minimal_png() -> bytes:
    """Return a valid 1×1 white PNG so we can test without uploading a file."""
    def chunk(name: bytes, data: bytes) -> bytes:
        c = struct.pack(">I", len(data)) + name + data
        return c + struct.pack(">I", zlib.crc32(name + data) & 0xFFFFFFFF)

    sig = b"\x89PNG\r\n\x1a\n"
    ihdr = chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0))
    raw = b"\x00\xff\xff\xff"  # filter byte + RGB white
    idat = chunk(b"IDAT", zlib.compress(raw))
    iend = chunk(b"IEND", b"")
    return sig + ihdr + idat + iend


@router.post("/debug/ollama-test")
async def ollama_test(file: Optional[UploadFile] = None):
    settings = get_settings()

    image_bytes = (await file.read()) if file else _minimal_png()
    b64 = base64.b64encode(image_bytes).decode()

    payload = {
        "model": settings.ollama_vision_model,
        "messages": [
            {
                "role": "user",
                "content": "Describe this image in one sentence.",
                "images": [b64[:80] + "…(truncated)"],  # truncate for display only
            }
        ],
        "stream": False,
    }

    # Build the real payload (full base64) for the actual request
    real_payload = {
        "model": settings.ollama_vision_model,
        "messages": [
            {
                "role": "user",
                "content": "Describe this image in one sentence.",
                "images": [b64],
            }
        ],
        "stream": False,
    }

    ollama_url = f"{settings.ollama_url}/api/chat"

    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(ollama_url, json=real_payload)
            return {
                "ollama_url": ollama_url,
                "model": settings.ollama_vision_model,
                "request_payload_preview": payload,
                "image_bytes": len(image_bytes),
                "b64_length": len(b64),
                "status_code": resp.status_code,
                "response_body": resp.json() if resp.headers.get("content-type", "").startswith("application/json") else resp.text,
                "success": resp.is_success,
            }
    except Exception as e:
        return {
            "ollama_url": ollama_url,
            "model": settings.ollama_vision_model,
            "error": str(e),
            "success": False,
        }
