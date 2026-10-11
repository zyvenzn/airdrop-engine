from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.security import rate_limit


class FakeRedis:
    def __init__(self, counts=None, error=None):
        self.counts = counts or {}
        self.error = error
        self.closed = False

    def incr(self, key):
        if self.error:
            raise self.error
        self.counts[key] = self.counts.get(key, 0) + 1
        return self.counts[key]

    def expire(self, key, seconds):
        if self.error:
            raise self.error
        return True

    def close(self):
        self.closed = True


def _request(host="203.0.113.10"):
    return SimpleNamespace(client=SimpleNamespace(host=host), headers={})


def test_rate_limit_allows_requests_under_limit(monkeypatch):
    fake = FakeRedis()
    monkeypatch.setattr(rate_limit.Redis, "from_url", lambda *a, **kw: fake)
    monkeypatch.setattr(rate_limit.settings, "redis_url", "redis://test/0")

    rate_limit.enforce_rate_limit(
        _request(), action="test", limit=2, window_seconds=60
    )
    rate_limit.enforce_rate_limit(
        _request(), action="test", limit=2, window_seconds=60
    )

    assert len(fake.counts) == 1
    assert list(fake.counts.values()) == [2]
    assert fake.closed


def test_rate_limit_rejects_request_over_limit(monkeypatch):
    fake = FakeRedis()
    monkeypatch.setattr(rate_limit.Redis, "from_url", lambda *a, **kw: fake)

    rate_limit.enforce_rate_limit(
        _request(), action="test", limit=1, window_seconds=60
    )

    with pytest.raises(HTTPException) as exc:
        rate_limit.enforce_rate_limit(
            _request(), action="test", limit=1, window_seconds=60
        )

    assert exc.value.status_code == 429
    assert exc.value.headers["Retry-After"] == "60"
    assert fake.closed


def test_rate_limit_fails_closed_when_redis_is_unavailable(monkeypatch):
    from redis.exceptions import ConnectionError as RedisConnectionError

    fake = FakeRedis(error=RedisConnectionError("offline"))
    monkeypatch.setattr(rate_limit.Redis, "from_url", lambda *a, **kw: fake)

    with pytest.raises(HTTPException) as exc:
        rate_limit.enforce_rate_limit(
            _request(), action="test", limit=1, window_seconds=60
        )

    assert exc.value.status_code == 503
    assert fake.closed


def test_client_fingerprint_ignores_untrusted_forwarded_header():
    request = _request()
    request.headers["x-forwarded-for"] = "198.51.100.7"

    assert rate_limit.client_fingerprint(request) == rate_limit.client_fingerprint(_request())
    assert rate_limit.client_fingerprint(request) != rate_limit.client_fingerprint(_request("203.0.113.11"))
