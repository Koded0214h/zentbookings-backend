#!/usr/bin/env python
"""Seed the catalogue with 72 Lagos luxury properties (8 pages x 9 for the frontend).

    uv run python scripts/seed_properties.py           # no-op if table already has rows
    uv run python scripts/seed_properties.py --force    # wipe and reseed
"""

from __future__ import annotations

import asyncio
import random
import sys

from sqlalchemy import delete, func, select

from app.core.database import SessionLocal
from app.models.property import Property

random.seed(20260830)

LOCATIONS = [
    "Victoria Island, Lagos", "Ikoyi, Lagos", "Banana Island, Lagos",
    "Lekki Phase 1, Lagos", "Oniru, Lagos", "Ikate, Lekki, Lagos",
    "Chevron Drive, Lekki, Lagos", "Parkview Estate, Ikoyi, Lagos",
    "Osborne Foreshore, Ikoyi, Lagos", "Ikeja GRA, Lagos",
]
ADJ = ["Obsidian", "Marble", "Azure", "Onyx", "Celadon", "Ivory", "Cobalt",
       "Amber", "Verdant", "Slate", "Opal", "Cinder"]
NOUN = ["Loft", "Residence", "Penthouse", "Villa", "Court", "Heights",
        "Pavilion", "Terrace", "House", "Suites"]
AMENITIES = [
    "Smart Home System", "Private Pool", "24/7 Security", "Backup Power",
    "Gym", "Elevator", "Ocean View", "Rooftop Lounge", "EV Charging",
    "Concierge", "Home Cinema", "Wine Cellar", "Boys' Quarters",
    "Landscaped Garden", "CCTV", "Fibre Internet",
]
DOT_COLORS = ["#FFE501", "#FF5A5F", "#00C2A8", "#7C4DFF", "#111111"]
DESCRIPTIONS = [
    "Where Precision Meets Panorama", "A Study in Quiet Luxury",
    "Light, Space, and the Lagoon", "Designed for the Discerning",
    "Architecture with a Point of View", "Calm Above the City",
]


def _full_description(title: str, location: str, beds: int) -> str:
    return (
        f"{title} is a {beds}-bedroom statement residence in {location}. "
        "Floor-to-ceiling glazing frames the skyline while wide-plank oak, "
        "honed stone, and bespoke joinery ground the interior. The open "
        "kitchen is fitted with integrated appliances and a stone island; "
        "principal suite with dressing room and spa bath. Fully serviced, "
        "with dedicated parking, backup power, and round-the-clock security."
    )


def _make(i: int) -> Property:
    category = "Rent" if i % 3 else "Shortlet"
    period = "Per Month" if category == "Rent" else "Per Night"
    beds = random.randint(1, 5)
    baths = beds + random.randint(0, 1)
    title = f"The {random.choice(ADJ)} {random.choice(NOUN)}"
    location = random.choice(LOCATIONS)
    if category == "Rent":
        price = random.randrange(350_000, 2_600_000, 50_000)
    else:
        price = random.randrange(45_000, 460_000, 5_000)
    return Property(
        title=title,
        location=location,
        image=f"https://picsum.photos/seed/zent-{i}/1200/800",
        gallery=[f"https://picsum.photos/seed/zent-{i}-{n}/1200/800" for n in range(1, 6)],
        beds=beds,
        baths=baths,
        sqft=random.randrange(800, 5200, 100),
        price=price,
        period=period,
        year_built=random.randint(2015, 2024),
        amenities=random.sample(AMENITIES, k=random.randint(4, 8)),
        description=random.choice(DESCRIPTIONS),
        full_description=_full_description(title, location, beds),
        dot_color=random.choice(DOT_COLORS),
        category=category,
    )


async def main() -> int:
    force = "--force" in sys.argv[1:]
    async with SessionLocal() as db:
        count = int(await db.scalar(select(func.count()).select_from(Property)) or 0)
        if count and not force:
            print(f"{count} properties already present. Use --force to wipe and reseed.")
            return 0
        if count and force:
            await db.execute(delete(Property))
            print(f"deleted {count} existing rows")
        db.add_all([_make(i) for i in range(1, 73)])
        await db.commit()
        total = int(await db.scalar(select(func.count()).select_from(Property)) or 0)
    print(f"seeded. properties table now holds {total} rows.")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
