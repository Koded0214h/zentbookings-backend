from __future__ import annotations

from conftest import sample_property


# ---------------- list param validation ----------------
async def test_list_rejects_bad_pagination(client):
    assert (await client.get("/api/properties", params={"page": 0})).status_code == 422
    assert (await client.get("/api/properties", params={"limit": 0})).status_code == 422
    assert (await client.get("/api/properties", params={"limit": 101})).status_code == 422


async def test_list_rejects_negative_price(client):
    assert (await client.get("/api/properties", params={"priceMin": -1})).status_code == 422


async def test_list_rejects_unknown_sort(client):
    assert (await client.get("/api/properties", params={"sort": "cheapest"})).status_code == 422


async def test_price_min_greater_than_max_is_empty(client, seeded_properties):
    res = await client.get(
        "/api/properties", params={"priceMin": 9_000_000, "priceMax": 1, "limit": 100}
    )
    assert res.json()["total"] == 0


async def test_huge_page_returns_empty_not_error(client, seeded_properties):
    res = await client.get("/api/properties", params={"page": 9999, "limit": 10})
    assert res.status_code == 200
    assert res.json()["properties"] == []
    assert res.json()["total"] == 25


async def test_like_wildcards_are_literal_in_location(client, admin_auth, seeded_properties):
    # a naive %like% would match everything on "%"
    res = await client.get("/api/properties", params={"location": "%", "limit": 100})
    assert res.json()["total"] == 0
    res2 = await client.get("/api/properties", params={"q": "_", "limit": 100})
    assert res2.json()["total"] == 0


async def test_unknown_type_filter_returns_empty(client, seeded_properties):
    res = await client.get("/api/properties", params={"type": "Hourly", "limit": 100})
    assert res.json()["total"] == 0


async def test_amenities_filter_ignores_blank_entries(client, admin_auth):
    await client.post(
        "/api/properties",
        json=sample_property(title="A1", amenities=["Gym", "Pool"]),
        headers=admin_auth,
    )
    res = await client.get("/api/properties", params={"amenities": "gym,, ,"})
    assert res.json()["total"] == 1


# ---------------- detail ----------------
async def test_detail_non_integer_id_is_422(client):
    assert (await client.get("/api/properties/abc")).status_code == 422


async def test_detail_zero_and_negative_id(client):
    assert (await client.get("/api/properties/0")).status_code == 404
    # negative parses as int -> 404 (not found), not 422
    assert (await client.get("/api/properties/-5")).status_code in (404, 422)


# ---------------- create validation ----------------
async def test_create_rejects_bad_period_and_category(client, admin_auth):
    assert (
        await client.post(
            "/api/properties", json=sample_property(period="Per Week"), headers=admin_auth
        )
    ).status_code == 422
    assert (
        await client.post(
            "/api/properties", json=sample_property(category="Lease"), headers=admin_auth
        )
    ).status_code == 422


async def test_create_rejects_out_of_range_numbers(client, admin_auth):
    for bad in ({"beds": -1}, {"price": -100}, {"yearBuilt": 1700}, {"yearBuilt": 3000}):
        res = await client.post("/api/properties", json=sample_property(**bad), headers=admin_auth)
        assert res.status_code == 422, bad


async def test_create_blank_type_is_derived(client, admin_auth):
    res = await client.post(
        "/api/properties",
        json=sample_property(type="", period="Per Night", category="Shortlet"),
        headers=admin_auth,
    )
    assert res.status_code == 201
    assert res.json()["type"] == "Nightly"


async def test_create_requires_auth_and_verification(client, registered_user):
    # verified normal user is still not staff -> 403
    auth = {"Authorization": f"Bearer {registered_user['body']['token']}"}
    assert (
        await client.post("/api/properties", json=sample_property(), headers=auth)
    ).status_code == 403
    assert (await client.post("/api/properties", json=sample_property())).status_code in (401, 403)


# ---------------- update ----------------
async def test_update_empty_body_is_noop(client, admin_auth):
    pid = (await client.post("/api/properties", json=sample_property(), headers=admin_auth)).json()[
        "id"
    ]
    res = await client.put(f"/api/properties/{pid}", json={}, headers=admin_auth)
    assert res.status_code == 200
    assert res.json()["title"] == "The Obsidian Loft"


async def test_update_period_rederives_type_unless_type_given(client, admin_auth):
    pid = (
        await client.post(
            "/api/properties",
            json=sample_property(period="Per Month", category="Rent"),
            headers=admin_auth,
        )
    ).json()["id"]

    r1 = await client.put(
        f"/api/properties/{pid}", json={"period": "Per Night"}, headers=admin_auth
    )
    assert r1.json()["type"] == "Nightly"

    r2 = await client.put(
        f"/api/properties/{pid}",
        json={"period": "Per Month", "type": "Yearly"},
        headers=admin_auth,
    )
    assert r2.json()["type"] == "Yearly"


async def test_update_amenities_reindexes_search(client, admin_auth):
    pid = (
        await client.post(
            "/api/properties", json=sample_property(amenities=["Gym"]), headers=admin_auth
        )
    ).json()["id"]
    assert (await client.get("/api/properties", params={"amenities": "gym"})).json()["total"] == 1

    await client.put(f"/api/properties/{pid}", json={"amenities": ["Sauna"]}, headers=admin_auth)
    assert (await client.get("/api/properties", params={"amenities": "gym"})).json()["total"] == 0
    assert (await client.get("/api/properties", params={"amenities": "sauna"})).json()["total"] == 1


async def test_update_missing_property_404(client, admin_auth):
    assert (
        await client.put("/api/properties/999999", json={"price": 1}, headers=admin_auth)
    ).status_code == 404


# ---------------- delete / restore / purge ----------------
async def test_double_soft_delete_is_idempotent(client, admin_auth):
    pid = (await client.post("/api/properties", json=sample_property(), headers=admin_auth)).json()[
        "id"
    ]
    assert (await client.delete(f"/api/properties/{pid}", headers=admin_auth)).status_code == 204
    assert (await client.delete(f"/api/properties/{pid}", headers=admin_auth)).status_code == 204


async def test_restore_non_deleted_is_noop(client, admin_auth):
    pid = (await client.post("/api/properties", json=sample_property(), headers=admin_auth)).json()[
        "id"
    ]
    res = await client.post(f"/api/properties/{pid}/restore", headers=admin_auth)
    assert res.status_code == 200


async def test_restore_and_purge_missing_property_404(client, admin_auth):
    assert (
        await client.post("/api/properties/424242/restore", headers=admin_auth)
    ).status_code == 404
    assert (
        await client.delete("/api/properties/424242?purge=true", headers=admin_auth)
    ).status_code == 404


async def test_soft_deleted_property_excluded_from_updates(client, admin_auth):
    pid = (await client.post("/api/properties", json=sample_property(), headers=admin_auth)).json()[
        "id"
    ]
    await client.delete(f"/api/properties/{pid}", headers=admin_auth)
    assert (
        await client.put(f"/api/properties/{pid}", json={"price": 1}, headers=admin_auth)
    ).status_code == 404


# ---------------- caching ----------------
async def test_etag_differs_when_data_changes(client, admin_auth, seeded_properties):
    first = await client.get("/api/properties", params={"limit": 5})
    etag1 = first.headers["etag"]
    await client.post("/api/properties", json=sample_property(), headers=admin_auth)
    second = await client.get("/api/properties", params={"limit": 5})
    assert second.headers["etag"] != etag1
