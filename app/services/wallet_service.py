from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppError
from app.models.booking import PayoutRequest, Wallet, WalletTransaction
from app.models.staff import StaffSettings
from app.services.payment_providers import get_payment_provider


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
    transaction_type: str = "CREDIT",
) -> Wallet:
    wallet = await get_or_create_wallet(db, user_id)
    wallet.balance += amount
    db.add(
        WalletTransaction(
            user_id=user_id,
            booking_id=booking_id,
            type=transaction_type,
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


async def request_payout(db: AsyncSession, user_id: str, amount: int) -> PayoutRequest:
    if amount <= 0:
        raise AppError(422, "validation_error", "Payout amount must be greater than zero.")
    settings = await db.get(StaffSettings, user_id)
    if not settings or not all(
        (
            settings.payout_bank_code,
            settings.payout_bank_name,
            settings.payout_account_number,
            settings.payout_account_name,
        )
    ):
        raise AppError(422, "payout_account_required", "Complete your payout bank details first.")

    wallet = await db.scalar(select(Wallet).where(Wallet.user_id == user_id).with_for_update())
    if wallet is None or wallet.balance < amount:
        raise AppError(409, "insufficient_wallet_balance", "Insufficient available balance.")
    await debit(db, user_id, amount, note="Funds reserved for payout request")
    row = PayoutRequest(
        agent_id=user_id,
        amount=amount,
        currency=wallet.currency,
        bank_code=settings.payout_bank_code,
        bank_name=settings.payout_bank_name,
        account_number=settings.payout_account_number,
        account_name=settings.payout_account_name,
    )
    db.add(row)
    await db.flush()
    return row


async def get_payout(
    db: AsyncSession, payout_id: str, *, for_update: bool = False
) -> PayoutRequest:
    stmt = select(PayoutRequest).where(PayoutRequest.id == payout_id)
    if for_update:
        stmt = stmt.with_for_update()
    row = await db.scalar(stmt)
    if row is None:
        raise AppError(404, "payout_not_found", "Payout request not found.")
    return row


async def review_payout(
    db: AsyncSession,
    payout_id: str,
    *,
    admin_id: str,
    approve: bool,
    note: str | None = None,
    transfer_reference: str | None = None,
) -> PayoutRequest:
    row = await get_payout(db, payout_id, for_update=True)
    if row.status != "PENDING":
        raise AppError(409, "payout_already_reviewed", "Payout request was already reviewed.")
    if approve and not transfer_reference:
        transfer = await get_payment_provider().disburse_to_bank(
            amount_naira=row.amount,
            account_name=row.account_name,
            account_number=row.account_number,
            bank_code=row.bank_code,
            reference=f"zent-{row.id}",
            reason=f"Zent agent payout {row.id}",
        )
        transfer_reference = transfer.get("reference") or transfer.get("transfer_code")
        if not transfer_reference:
            raise AppError(502, "bachs_error", "Payout response had no reference.")
    row.status = "APPROVED" if approve else "REJECTED"
    row.reviewed_by = admin_id
    row.reviewed_at = datetime.now(UTC)
    row.admin_note = note
    row.transfer_reference = transfer_reference if approve else None
    if not approve:
        await credit(
            db,
            row.agent_id,
            row.amount,
            note=f"Rejected payout {row.id} returned to wallet",
            transaction_type="REFUND",
        )
    await db.flush()
    return row


async def list_payouts(
    db: AsyncSession, *, user_id: str | None = None, status: str | None = None
) -> list[PayoutRequest]:
    stmt = select(PayoutRequest)
    if user_id:
        stmt = stmt.where(PayoutRequest.agent_id == user_id)
    if status:
        if status not in ("PENDING", "APPROVED", "DISBURSED", "REJECTED", "FAILED"):
            raise AppError(422, "validation_error", "Invalid payout status.")
        stmt = stmt.where(PayoutRequest.status == status)
    rows = await db.scalars(stmt.order_by(PayoutRequest.created_at.desc()))
    return list(rows.all())


async def process_transfer_event(
    db: AsyncSession, *, reference: str, succeeded: bool
) -> PayoutRequest | None:
    row = await db.scalar(
        select(PayoutRequest)
        .where(PayoutRequest.transfer_reference == reference)
        .with_for_update()
    )
    if row is None or row.status != "APPROVED":
        return row
    if succeeded:
        row.status = "DISBURSED"
    else:
        row.status = "FAILED"
        await credit(
            db,
            row.agent_id,
            row.amount,
            note=f"Failed payout {row.id} returned to wallet",
            transaction_type="REFUND",
        )
    await db.flush()
    return row


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
