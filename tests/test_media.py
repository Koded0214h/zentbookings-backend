from __future__ import annotations

import io

import pytest
from conftest import sample_property

from app.services import media


@pytest.fixture
def fake_cloudinary(monkeypatch):
    calls: dict[str, list] = {"upload": [], "destroy": [], "sign": 0}

    async def fake_upload_bytes(data: bytes, *, resource_type: str = "image") -> dict:
        calls["upload"].append((len(data), resource_type))
        n = len(calls["upload"])
        return {
            "url": f"https://res.cloudinary.com/doarhpvhv/{resource_type}/upload/v1/zent/properties/pic{n}.jpg",
            "public_id": f"zent/properties/pic{n}",
            "resource_type": resource_type,
            "format": "jpg",
            "bytes": len(data),
            "width": 1200,
            "height": 800,
        }

    async def fake_destroy(public_id: str, *, resource_type: str = "image") -> bool:
        calls["destroy"].append((public_id, resource_type))
        return True

    def fake_sign(extra=None) -> dict:
        calls["sign"] += 1
        return {
            "cloud_name": "doarhpvhv",
            "api_key": "541427483985585",
            "signature": "deadbeef",
            "timestamp": 1788130000,
            "folder": "zent/properties",
        }

    monkeypatch.setattr(media, "upload_bytes", fake_upload_bytes)
    monkeypatch.setattr(media, "destroy", fake_destroy)
    monkeypatch.setattr(media, "sign_upload", fake_sign)
    return calls


async def test_upload_requires_staff(client, registered_user):
    token = registered_user["body"]["token"]
    res = await client.post(
        "/api/media/upload",
        files={"files": ("a.jpg", b"x", "image/jpeg")},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res.status_code == 403


async def test_upload_requires_auth(client):
    res = await client.post(
        "/api/media/upload", files={"files": ("a.jpg", b"x", "image/jpeg")}
    )
    assert res.status_code in (401, 403)


async def test_upload_returns_asset_list(client, admin_auth, fake_cloudinary):
    res = await client.post(
        "/api/media/upload",
        files=[
            ("files", ("a.jpg", io.BytesIO(b"aaaa"), "image/jpeg")),
            ("files", ("b.jpg", io.BytesIO(b"bbbbbb"), "image/jpeg")),
        ],
        headers=admin_auth,
    )
    assert res.status_code == 200, res.text
    assets = res.json()["assets"]
    assert len(assets) == 2
    assert assets[0]["publicId"] == "zent/properties/pic1"
    assert assets[0]["url"].startswith("https://res.cloudinary.com/")
    assert len(fake_cloudinary["upload"]) == 2


async def test_sign_endpoint(client, admin_auth, fake_cloudinary):
    res = await client.post("/api/media/sign", headers=admin_auth)
    assert res.status_code == 200
    body = res.json()
    assert body["cloudName"] == "doarhpvhv"
    assert body["signature"] == "deadbeef"
    assert body["folder"] == "zent/properties"
    assert fake_cloudinary["sign"] == 1


async def test_delete_endpoint(client, admin_auth, fake_cloudinary):
    res = await client.post(
        "/api/media/delete",
        json={"publicId": "zent/properties/pic1", "resourceType": "image"},
        headers=admin_auth,
    )
    assert res.status_code == 200
    assert res.json() == {"deleted": True}
    assert fake_cloudinary["destroy"] == [("zent/properties/pic1", "image")]


async def test_property_put_cleans_replaced_assets(client, admin_auth, fake_cloudinary):
    created = await client.post(
        "/api/properties",
        json=sample_property(
            imagePublicId="zent/properties/hero-old",
            galleryPublicIds=["zent/properties/g1", "zent/properties/g2"],
        ),
        headers=admin_auth,
    )
    pid = created.json()["id"]

    # swap the hero image, keep g2, drop g1, add g3
    res = await client.put(
        f"/api/properties/{pid}",
        json={
            "imagePublicId": "zent/properties/hero-new",
            "galleryPublicIds": ["zent/properties/g2", "zent/properties/g3"],
        },
        headers=admin_auth,
    )
    assert res.status_code == 200

    destroyed = {c[0] for c in fake_cloudinary["destroy"]}
    assert destroyed == {"zent/properties/hero-old", "zent/properties/g1"}


async def test_property_purge_cleans_cloudinary_assets(client, admin_auth, fake_cloudinary):
    created = await client.post(
        "/api/properties",
        json=sample_property(
            imagePublicId="zent/properties/hero",
            galleryPublicIds=["zent/properties/g1", "zent/properties/g2"],
        ),
        headers=admin_auth,
    )
    assert created.status_code == 201, created.text
    pid = created.json()["id"]
    # public ids are stored, not echoed
    assert "imagePublicId" not in created.json()

    # plain (soft) delete keeps the assets
    soft = await client.delete(f"/api/properties/{pid}", headers=admin_auth)
    assert soft.status_code == 204
    assert fake_cloudinary["destroy"] == []

    # purge hard-deletes and destroys them
    purged = await client.delete(f"/api/properties/{pid}?purge=true", headers=admin_auth)
    assert purged.status_code == 204

    destroyed = {c[0] for c in fake_cloudinary["destroy"]}
    assert destroyed == {
        "zent/properties/hero",
        "zent/properties/g1",
        "zent/properties/g2",
    }
