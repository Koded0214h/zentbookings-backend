from __future__ import annotations

import httpx
import pytest

from app.core.config import settings
from app.services import nin_verification
from app.services.nin_verification import NinVerificationFailed

_REAL_ASYNC_CLIENT = httpx.AsyncClient


class _FakeClient:
    def __init__(self, handler, **kwargs):
        self._client = _REAL_ASYNC_CLIENT(transport=httpx.MockTransport(handler), **kwargs)

    async def __aenter__(self):
        return await self._client.__aenter__()

    async def __aexit__(self, *args):
        return await self._client.__aexit__(*args)


@pytest.mark.asyncio
async def test_ninja_verify_accepts_matching_identity(monkeypatch):
    monkeypatch.setattr(settings, "NINJA_SECRET_KEY", "sk_sandbox_test")
    monkeypatch.setattr(settings, "NINJA_BASE_URL", None)
    seen = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["authorization"] = request.headers["authorization"]
        seen["payload"] = __import__("json").loads(request.content)
        return httpx.Response(
            200,
            json={
                "found": True,
                "verified": True,
                "score": 1,
                "recommendation": "accept",
                "request_id": "req_test",
            },
        )

    monkeypatch.setattr(
        nin_verification.httpx,
        "AsyncClient",
        lambda **kwargs: _FakeClient(handler, **kwargs),
    )
    result = await nin_verification.verify_nin(
        "77777777777", first_name="James", last_name="Bond"
    )

    assert seen == {
        "url": "https://api.sandbox.ninja.boucloud.io/api/identity/identify",
        "authorization": "Bearer sk_sandbox_test",
        "payload": {
            "idType": "nin",
            "mode": "verify",
            "idNumber": "77777777777",
            "firstName": "James",
            "lastName": "Bond",
        },
    }
    assert result.registered_name == "James Bond"
    assert result.reference == "req_test"


@pytest.mark.asyncio
async def test_ninja_verify_rejects_mismatch(monkeypatch):
    monkeypatch.setattr(settings, "NINJA_SECRET_KEY", "sk_live_test")
    monkeypatch.setattr(settings, "NINJA_BASE_URL", None)

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "found": True,
                "verified": False,
                "score": 0.4,
                "recommendation": "reject",
            },
        )

    monkeypatch.setattr(
        nin_verification.httpx,
        "AsyncClient",
        lambda **kwargs: _FakeClient(handler, **kwargs),
    )
    with pytest.raises(NinVerificationFailed):
        await nin_verification.verify_nin(
            "12345678901", first_name="Wrong", last_name="Name"
        )
