import json
from datetime import date, datetime, timedelta
from typing import Optional

import redis.asyncio as aioredis

from app.config import get_settings

settings = get_settings()

_redis_client: Optional[aioredis.Redis] = None


def get_redis_client() -> aioredis.Redis:
    global _redis_client
    if _redis_client is None:
        _redis_client = aioredis.from_url(
            settings.redis_url,
            encoding="utf-8",
            decode_responses=True,
        )
    return _redis_client


async def get_claim_status(claim_id: str) -> Optional[dict]:
    client = get_redis_client()
    val = await client.get(f"claim_status:{claim_id}")
    if val:
        return json.loads(val)
    return None


async def set_claim_status(claim_id: str, status: str, decision: Optional[str] = None) -> None:
    client = get_redis_client()
    payload = {"status": status, "decision": decision}
    await client.setex(f"claim_status:{claim_id}", 86400, json.dumps(payload))


async def delete_claim_status(claim_id: str) -> None:
    client = get_redis_client()
    await client.delete(f"claim_status:{claim_id}")


async def get_member_cache(member_id: str) -> Optional[dict]:
    client = get_redis_client()
    val = await client.get(f"member:{member_id}")
    if val:
        return json.loads(val)
    return None


async def set_member_cache(member_id: str, member_data: dict) -> None:
    client = get_redis_client()
    await client.setex(f"member:{member_id}", 3600, json.dumps(member_data, default=str))


async def get_same_day_count(member_id: str, treatment_date: date) -> int:
    client = get_redis_client()
    key = f"fraud:same_day:{member_id}:{treatment_date.isoformat()}"
    val = await client.get(key)
    return int(val) if val else 0


async def increment_same_day_count(member_id: str, treatment_date: date) -> int:
    client = get_redis_client()
    key = f"fraud:same_day:{member_id}:{treatment_date.isoformat()}"
    count = await client.incr(key)
    # Expire at midnight of the treatment date + 1 day
    midnight = datetime.combine(treatment_date + timedelta(days=1), datetime.min.time())
    ttl = int((midnight - datetime.utcnow()).total_seconds())
    if ttl > 0:
        await client.expire(key, ttl)
    return count


async def get_monthly_count(member_id: str, year_month: str) -> int:
    client = get_redis_client()
    key = f"fraud:monthly:{member_id}:{year_month}"
    val = await client.get(key)
    return int(val) if val else 0


async def increment_monthly_count(member_id: str, year_month: str) -> int:
    client = get_redis_client()
    key = f"fraud:monthly:{member_id}:{year_month}"
    count = await client.incr(key)
    await client.expire(key, 35 * 24 * 3600)
    return count


async def set_policy_cache(policy_id: str, policy_data: dict) -> None:
    client = get_redis_client()
    await client.setex(f"policy:{policy_id}", 3600, json.dumps(policy_data))


async def get_policy_cache(policy_id: str) -> Optional[dict]:
    client = get_redis_client()
    val = await client.get(f"policy:{policy_id}")
    if val:
        return json.loads(val)
    return None


async def mark_embedding_model_loaded() -> None:
    client = get_redis_client()
    await client.set("embedding:model:loaded", "1")


async def is_embedding_model_loaded() -> bool:
    client = get_redis_client()
    val = await client.get("embedding:model:loaded")
    return val == "1"


async def ping() -> bool:
    try:
        client = get_redis_client()
        return await client.ping()
    except Exception:
        return False
