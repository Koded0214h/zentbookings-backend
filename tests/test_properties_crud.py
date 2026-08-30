from __future__ import annotations

from conftest import sample_property


async def test_create_requires_staff_role(client, registered_user):
    token = registered_user["body"]["token"]
    res = await client.post(
        "/api/properties",
        json=sample_property(),
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res.status_code == 403
    assert res.json()["error"]["code"] == "forbidden"


async def test_create_requires_auth(client):
    res = await client.post("/api/properties", json=sample_property())
    assert res.status_code in (401, 403)


async def test_admin_full_crud_cycle(client, admin_auth):
    # create
    created = await client.post("/api/properties", json=sample_property(), headers=admin_auth)
    assert created.status_code == 201, created.text
    body = created.json()
    pid = body["id"]
    assert isinstance(pid, int)
    assert body["title"] == "The Obsidian Loft"
    assert body["gallery"] == ["https://cdn.zentbookings.com/images/prop-1-1.jpg"]

    # visible on the public listing
    listing = (await client.get("/api/properties")).json()
    assert listing["total"] == 1

    # partial update
    updated = await client.put(
        f"/api/properties/{pid}",
        json={"price": 999000, "amenities": ["Gym"]},
        headers=admin_auth,
    )
    assert updated.status_code == 200
    assert updated.json()["price"] == 999000
    assert updated.json()["amenities"] == ["Gym"]
    assert updated.json()["title"] == "The Obsidian Loft"  # untouched

    # delete
    deleted = await client.delete(f"/api/properties/{pid}", headers=admin_auth)
    assert deleted.status_code == 204
    assert (await client.get(f"/api/properties/{pid}")).status_code == 404


async def test_create_validation_rejects_bad_enum(client, admin_auth):
    res = await client.post(
        "/api/properties",
        json=sample_property(category="Lease"),
        headers=admin_auth,
    )
    assert res.status_code == 422


async def test_update_missing_property_404(client, admin_auth):
    res = await client.put(
        "/api/properties/424242", json={"price": 1}, headers=admin_auth
    )
    assert res.status_code == 404
