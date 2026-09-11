from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.booking import ACTIVE_BOOKING_STATUSES, Booking, Wallet, WalletTransaction
from app.models.property import Property


async def agent_dashboard(
    db: AsyncSession, *, user_id: str, property_ids: list[int] | None, admin_wide: bool
) -> dict:
    """`property_ids=None` + `admin_wide=True` means "all properties, platform-wide
    totals" (the admin view); otherwise scoped to the caller's own wallet and
    assigned properties (the agent view)."""
    listings_stmt = select(func.count()).select_from(Property).where(Property.deleted_at.is_(None))
    bookings_stmt = select(func.count()).select_from(Booking).where(
        Booking.status.in_(ACTIVE_BOOKING_STATUSES)
    )
    if property_ids is not None:
        ids = property_ids or [-1]
        listings_stmt = listings_stmt.where(Property.id.in_(ids))
        bookings_stmt = bookings_stmt.where(Booking.property_id.in_(ids))

    total_listings = int(await db.scalar(listings_stmt) or 0)
    active_bookings = int(await db.scalar(bookings_stmt) or 0)

    credit_stmt = select(WalletTransaction.created_at, WalletTransaction.amount).where(
        WalletTransaction.type == "CREDIT"
    )
    balance_stmt = select(func.coalesce(func.sum(Wallet.balance), 0))
    if not admin_wide:
        credit_stmt = credit_stmt.where(WalletTransaction.user_id == user_id)
        balance_stmt = balance_stmt.where(Wallet.user_id == user_id)

    rows = (await db.execute(credit_stmt)).all()
    total_earnings = sum(amount for _created_at, amount in rows)
    pending_payouts = int(await db.scalar(balance_stmt) or 0)

    buckets: dict[str, int] = {}
    for created_at, amount in rows:
        key = created_at.strftime("%Y-%m")
        buckets[key] = buckets.get(key, 0) + amount
    monthly_revenue = [{"month": k, "amount": v} for k, v in sorted(buckets.items())][-6:]

    return {
        "total_listings": total_listings,
        "active_bookings": active_bookings,
        "total_earnings": total_earnings,
        "pending_payouts": pending_payouts,
        "monthly_revenue": monthly_revenue,
    }
