from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.booking import Wallet, WalletTransaction


async def get_or_create_wallet(db: AsyncSession, user_id: str) -> Wallet:
    wallet = await db.get(Wallet, user_id)
    if wallet is None:
        wallet = Wallet(user_id=user_id)
        db.add(wallet)
        await db.flush()
    return wallet


async def credit(
    db: AsyncSession,
    user_id: str,
    amount: int,
    *,
    booking_id: str | None = None,
    note: str | None = None,
) -> Wallet:
    wallet = await get_or_create_wallet(db, user_id)
    wallet.balance += amount
    db.add(
        WalletTransaction(
            user_id=user_id,
            booking_id=booking_id,
            type="CREDIT",
            amount=amount,
            balance_after=wallet.balance,
            note=note,
        )
    )
    await db.flush()
    return wallet


async def debit(
    db: AsyncSession,
    user_id: str,
    amount: int,
    *,
    booking_id: str | None = None,
    note: str | None = None,
) -> Wallet:
    wallet = await get_or_create_wallet(db, user_id)
    wallet.balance -= amount
    db.add(
        WalletTransaction(
            user_id=user_id,
            booking_id=booking_id,
            type="DEBIT",
            amount=amount,
            balance_after=wallet.balance,
            note=note,
        )
    )
    await db.flush()
    return wallet


async def recent_transactions(
    db: AsyncSession, user_id: str, limit: int = 20
) -> list[WalletTransaction]:
    rows = (
        (
            await db.execute(
                select(WalletTransaction)
                .where(WalletTransaction.user_id == user_id)
                .order_by(WalletTransaction.created_at.desc())
                .limit(limit)
            )
        )
        .scalars()
        .all()
    )
    return list(rows)
