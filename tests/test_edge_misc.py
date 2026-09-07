from __future__ import annotations

import io

import pytest

from app.services import media


# ---------------- routing / error envelope ----------------
async def test_unknown_route_404_envelope(client):
    res = await client.get("/api/does-not-exist")
    assert res.status_code == 404
    assert res.json()["error"]["code"] == "not_found"


async def test_method_not_allowed(client):
    res = await client.patch("/api/auth/login", json={})
    assert res.status_code == 405
    assert "error" in res.json()


async def test_malformed_json_body(client):
    res = await client.post(
        "/api/auth/login",
        content=b"{not json",
        headers={"content-type": "application/json"},
    )
    assert res.status_code in (400, 422)
    assert "error" in res.json()


async def test_missing_required_field_lists_it(client):
    res = await client.post("/api/auth/register", json={"email": "x@example.com"})
    assert res.status_code == 422
    body = res.json()
    assert body["error"]["code"] == "validation_error"
    assert any("password" in f["field"] for f in body["error"]["fields"])


async def test_health_and_request_id_header(client):
    res = await client.get("/health")
    assert res.status_code == 200
    r2 = await client.get("/api/properties")
    assert r2.headers.get("x-request-id")


# ---------------- media ----------------
@pytest.fixture
def fake_media(monkeypatch):
    calls = {"upload": 0, "destroy": []}

    async def up(data, *, resource_type="image"):
        calls["upload"] += 1
        return {
            "url": "https://res.cloudinary.com/x/image/upload/v1/zent/properties/a.jpg",
            "public_id": "zent/properties/a",
            "resource_type": resource_type,
            "format": "jpg",
            "bytes": len(data),
            "width": 1,
            "height": 1,
        }

    async def destroy(pid, *, resource_type="image"):
        calls["destroy"].append(pid)
        return True

    monkeypatch.setattr(media, "upload_bytes", up)
    monkeypatch.setattr(media, "destroy", destroy)
    return calls


async def test_media_upload_no_file_is_422(client, admin_auth):
    res = await client.post("/api/media/upload", headers=admin_auth)
    assert res.status_code == 422


async def test_media_upload_oversize_is_413(client, admin_auth, monkeypatch):
    monkeypatch.setattr(media, "_MAX_BYTES", 8)
    res = await client.post(
        "/api/media/upload",
        files={"files": ("big.jpg", io.BytesIO(b"x" * 40), "image/jpeg")},
        headers=admin_auth,
    )
    assert res.status_code == 413
    assert res.json()["error"]["code"] == "file_too_large"


async def test_media_upload_bad_resource_type(client, admin_auth):
    res = await client.post(
        "/api/media/upload",
        files={"files": ("a.jpg", io.BytesIO(b"xxxx"), "image/jpeg")},
        data={"resource_type": "hologram"},
        headers=admin_auth,
    )
    assert res.status_code in (400, 502)


async def test_media_endpoints_reject_non_staff(client, registered_user):
    auth = {"Authorization": f"Bearer {registered_user['body']['token']}"}
    assert (await client.post("/api/media/sign", headers=auth)).status_code == 403
    assert (
        await client.post(
            "/api/media/delete", json={"publicId": "x", "resourceType": "image"}, headers=auth
        )
    ).status_code == 403


async def test_media_delete_unknown_id(client, admin_auth, fake_media):
    res = await client.post(
        "/api/media/delete",
        json={"publicId": "zent/properties/nope", "resourceType": "image"},
        headers=admin_auth,
    )
    assert res.status_code == 200


# ---------------- observability ----------------
async def test_observability_public_and_counts(client):
    await client.get("/api/properties")
    m = (await client.get("/observability/metrics")).json()
    assert m["totalRequests"] >= 1
    assert set(m["latencyMs"]) == {"p50", "p90", "p99", "max", "avg"}


async def test_observability_ignores_own_and_health(client):
    for _ in range(3):
        await client.get("/observability/metrics")
        await client.get("/health")
    routes = {r["route"] for r in (await client.get("/observability/metrics")).json()["topRoutes"]}
    assert not any(r.startswith("/observability") or r == "/health" for r in routes)


async def test_observability_redacts_sensitive_query(client):
    await client.post(
        "/api/auth/verify-otp?token=SECRETLEAK", json={"email": "x@y.com", "code": "1"}
    )
    logs = (await client.get("/observability/logs")).json()
    joined = str(logs["recentRequests"])
    assert "SECRETLEAK" not in joined
