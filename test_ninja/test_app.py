import httpx
import pytest

from test_ninja.app import app


@pytest.mark.asyncio
async def test_verify_uses_sandbox_verify_mode(monkeypatch):
    monkeypatch.setenv("NINJA_TEST_SECRET_KEY", "sk_sandbox_test")
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
                "score": 1.0,
                "recommendation": "accept",
                "fields": [{"field": "first_name", "match": "exact", "provided": "James"}],
            },
        )

    real_client = httpx.AsyncClient

    class FakeNinjaClient:
        def __init__(self, **kwargs):
            self.client = real_client(transport=httpx.MockTransport(handler), **kwargs)

        async def __aenter__(self):
            return await self.client.__aenter__()

        async def __aexit__(self, *args):
            return await self.client.__aexit__(*args)

    monkeypatch.setattr(
        "test_ninja.app.httpx.AsyncClient",
        FakeNinjaClient,
    )
    transport = httpx.ASGITransport(app=app)
    async with real_client(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/verify",
            data={
                "nin": "77777777777",
                "first_name": "James",
                "last_name": "Bond",
                "date_of_birth": "1975-01-01",
            },
        )

    assert response.status_code == 200
    assert seen["url"] == "https://api.sandbox.ninja.boucloud.io/api/identity/identify"
    assert seen["authorization"] == "Bearer sk_sandbox_test"
    assert seen["payload"] == {
        "idType": "nin",
        "mode": "verify",
        "idNumber": "77777777777",
        "firstName": "James",
        "lastName": "Bond",
        "dateOfBirth": "1975-01-01",
    }
    assert "77777777777" not in response.text
    assert "James" not in response.text
    assert "accept" in response.text


@pytest.mark.asyncio
async def test_rejects_invalid_nin_before_api_call(monkeypatch):
    monkeypatch.setenv("NINJA_TEST_SECRET_KEY", "sk_sandbox_test")
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/verify",
            data={"nin": "123", "first_name": "James", "last_name": "Bond"},
        )
    assert response.status_code == 422
