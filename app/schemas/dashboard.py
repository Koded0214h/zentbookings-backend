from __future__ import annotations

from app.schemas.common import CamelModel


class RevenuePoint(CamelModel):
    month: str  # "YYYY-MM"
    amount: int


class DashboardOut(CamelModel):
    total_listings: int
    active_bookings: int
    total_earnings: int
    pending_payouts: int
    monthly_revenue: list[RevenuePoint]
