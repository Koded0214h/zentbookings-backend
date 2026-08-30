from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.services import maintenance, media


@pytest.mark.parametrize(
    "url,expected",
    [
        (
            "https://res.cloudinary.com/doarhpvhv/image/upload/v1788130436/zent/properties/abc123.png",
            "zent/properties/abc123",
        ),
        (
            "https://res.cloudinary.com/doarhpvhv/image/upload/w_400,h_300,c_fill/v1788130436/zent/properties/abc123.jpg",
            "zent/properties/abc123",
        ),
        (
            "https://res.cloudinary.com/doarhpvhv/image/upload/zent/properties/noversion.webp",
            "zent/properties/noversion",
        ),
        ("https://picsum.photos/seed/zent-1/1200/800", None),
        ("", None),
        (None, None),
    ],
)
def test_public_id_from_url(url, expected):
    assert media.public_id_from_url(url) == expected


async def test_sweep_destroys_only_unreferenced_and_aged(
    session_factory, admin_auth, client, monkeypatch
):
    # one property that references an image by public id and a gallery item by URL
    created = await client.post(
        "/api/properties",
        json={
            "title": "Keeper",
            "location": "Ikoyi, Lagos",
            "image": "https://cdn.zentbookings.com/x.jpg",
            "imagePublicId": "zent/properties/keep-me",
            "gallery": [
                "https://res.cloudinary.com/doarhpvhv/image/upload/v1/zent/properties/keep-url.jpg"
            ],
            "galleryPublicIds": [],
            "beds": 1, "baths": 1, "sqft": 1, "price": 1, "period": "Per Month",
            "yearBuilt": 2020, "amenities": [], "description": "d",
            "fullDescription": "f", "dotColor": "#111", "category": "Rent",
        },
        headers=admin_auth,
    )
    assert created.status_code == 201

    now = datetime.now(UTC)
    old = (now - timedelta(days=3)).strftime("%Y-%m-%dT%H:%M:%SZ")
    fresh = (now - timedelta(minutes=5)).strftime("%Y-%m-%dT%H:%M:%SZ")

    async def fake_list_assets(*, resource_type="image"):
        if resource_type != "image":
            return []
        return [
            {"public_id": "zent/properties/keep-me", "created_at": old},
            {"public_id": "zent/properties/keep-url", "created_at": old},
            {"public_id": "zent/properties/orphan-old", "created_at": old},
            {"public_id": "zent/properties/orphan-fresh", "created_at": fresh},
        ]

    destroyed: list[str] = []

    async def fake_destroy(public_id, *, resource_type="image"):
        destroyed.append(public_id)
        return True

    monkeypatch.setattr(media, "list_assets", fake_list_assets)
    monkeypatch.setattr(media, "destroy", fake_destroy)
    monkeypatch.setattr(maintenance.settings, "MEDIA_SWEEP_ENABLED", True)
    monkeypatch.setattr(
        type(maintenance.settings), "cloudinary_configured", property(lambda self: True)
    )

    async with session_factory() as db:
        removed = await maintenance.sweep_orphan_media(db, now=now)

    assert removed == 1
    assert destroyed == ["zent/properties/orphan-old"]
