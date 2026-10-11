import hashlib
from fastapi import HTTPException, Request, status
from redis import Redis
from redis.exceptions import RedisError

from app.config import settings


def client_fingerprint(request: Request) -> str:
    # Do not use arbitrary X-Forwarded-For unless a trusted proxy is configured.
    host = request.client.host if request.client else "unknown"
    return hashlib.sha256(host.encode()).hexdigest()[:24]


def enforce_rate_limit(
    request: Request,
    *,
    action: str,
    limit: int,
    window_seconds: int,
) -> None:
    if limit < 1 or window_seconds < 1:
        raise ValueError("rate limit parameters must be positive")
    redis = Redis.from_url(settings.redis_url, decode_responses=True, socket_timeout=1)
    key = f"rate:{action}:{client_fingerprint(request)}"
    try:
        count = redis.incr(key)
        if count == 1:
            redis.expire(key, window_seconds)
        if count > limit:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Rate limit exceeded",
                headers={"Retry-After": str(window_seconds)},
            )
    except RedisError as exc:
        # Fail closed for protected endpoints; availability should be restored by ops.
        raise HTTPException(status_code=503, detail="Rate limiter unavailable") from exc
    finally:
        redis.close()
