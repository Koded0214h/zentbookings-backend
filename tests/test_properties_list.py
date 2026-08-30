from __future__ import annotations

from conftest import sample_property


async def test_list_empty(client):
    res = await client.get("/api/properties")
    assert res.status_code == 200
    body = res.json()
    assert body == {"properties": [], "total": 0, "page": 1, "limit": 9, "totalPages": 0}


async def test_list_pagination_envelope(client, seeded_properties):
    res = await client.get("/api/properties", params={"page": 1, "limit": 9})
    body = res.json()
    assert body["total"] == 25
    assert body["limit"] == 9
    assert body["page"] == 1
    assert body["totalPages"] == 3
    assert len(body["properties"]) == 9

    page3 = (await client.get("/api/properties", params={"page": 3, "limit": 9})).json()
    assert len(page3["properties"]) == 7  # 25 - 18

    page4 = (await client.get("/api/properties", params={"page": 4, "limit": 9})).json()
    assert page4["properties"] == []


async def test_filter_by_category(client, seeded_properties):
    rent = (await client.get("/api/properties", params={"category": "Rent", "limit": 100})).json()
    assert rent["total"] == 12
    assert {p["category"] for p in rent["properties"]} == {"Rent"}

    # case-insensitive
    lc = (await client.get("/api/properties", params={"category": "shortlet", "limit": 100})).json()
    assert lc["total"] == 13


async def test_filter_by_location_partial_ci(client, seeded_properties):
    res = (await client.get("/api/properties", params={"location": "lekki", "limit": 100})).json()
    assert res["total"] > 0
    assert all("Lekki" in p["location"] for p in res["properties"])


async def test_filter_by_price_range(client, seeded_properties):
    res = (
        await client.get(
            "/api/properties",
            params={"priceMin": 300_000, "priceMax": 900_000, "limit": 100},
        )
    ).json()
    assert res["total"] > 0
    assert all(300_000 <= p["price"] <= 900_000 for p in res["properties"])


async def test_type_param_maps_to_period(client, seeded_properties):
    monthly = (
        await client.get("/api/properties", params={"type": "Monthly", "limit": 100})
    ).json()
    assert monthly["total"] > 0
    assert all(p["period"] == "Per Month" for p in monthly["properties"])

    nightly = (
        await client.get("/api/properties", params={"type": "Nightly", "limit": 100})
    ).json()
    assert all(p["period"] == "Per Night" for p in nightly["properties"])


async def test_sort_by_price(client, seeded_properties):
    asc = (await client.get("/api/properties", params={"sort": "price", "limit": 100})).json()
    prices = [p["price"] for p in asc["properties"]]
    assert prices == sorted(prices)

    desc = (await client.get("/api/properties", params={"sort": "-price", "limit": 100})).json()
    prices_d = [p["price"] for p in desc["properties"]]
    assert prices_d == sorted(prices_d, reverse=True)


async def test_sort_rejects_unknown_value(client, seeded_properties):
    res = await client.get("/api/properties", params={"sort": "bogus"})
    assert res.status_code == 422


async def test_free_text_search(client, admin_auth):
    for title in ("Skyline Penthouse", "Garden Maisonette", "Skyline Studio"):
        await client.post(
            "/api/properties",
            json=sample_property(title=title),
            headers=admin_auth,
        )
    res = (await client.get("/api/properties", params={"q": "skyline"})).json()
    assert res["total"] == 2
    assert {p["title"] for p in res["properties"]} == {"Skyline Penthouse", "Skyline Studio"}


async def test_etag_returns_304(client, seeded_properties):
    first = await client.get("/api/properties", params={"limit": 5})
    assert first.status_code == 200
    etag = first.headers["etag"]
    assert first.headers["cache-control"].startswith("public, max-age=")

    again = await client.get(
        "/api/properties", params={"limit": 5}, headers={"If-None-Match": etag}
    )
    assert again.status_code == 304
    assert again.content == b""

    # a different query yields a different etag
    other = await client.get("/api/properties", params={"limit": 6})
    assert other.headers["etag"] != etag


async def test_get_detail_and_404(client, seeded_properties):
    listing = (await client.get("/api/properties", params={"limit": 1})).json()
    pid = listing["properties"][0]["id"]

    detail = await client.get(f"/api/properties/{pid}")
    assert detail.status_code == 200
    body = detail.json()
    assert body["id"] == pid
    assert "fullDescription" in body and "yearBuilt" in body

    missing = await client.get("/api/properties/999999")
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "property_not_found"
