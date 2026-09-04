from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated

import jwt
from fastapi import APIRouter, BackgroundTasks, Depends, Form, Query, Request, status
from fastapi.responses import RedirectResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.api.deps import CurrentUser, DbSession, TokenClaims
from app.core.config import settings
from app.core.exceptions import AppError, OAuthNotConfigured
from app.core.ratelimit import rate_limit
from app.core.security import create_access_token, decode_access_token
from app.models.user import User
from app.schemas.auth import (
    AuthResponse,
    ForgotPasswordRequest,
    LoginRequest,
    MessageResponse,
    RegisterRequest,
    RegisterResponse,
    ResendOtpRequest,
    ResetPasswordRequest,
    UserOut,
    VerifyOtpRequest,
)
from app.services import auth_service, oauth
from app.services.email import EmailSender, get_email_sender
from app.services.email import templates as tmpl

router = APIRouter(prefix="/auth", tags=["auth"])

_bearer = HTTPBearer(auto_error=True)
SenderDep = Annotated[EmailSender, Depends(get_email_sender)]

_login_limit = Depends(rate_limit("login", settings.LOGIN_RATE_LIMIT))
_register_limit = Depends(rate_limit("register", settings.REGISTER_RATE_LIMIT))
_forgot_limit = Depends(rate_limit("forgot_password", settings.FORGOT_PASSWORD_RATE_LIMIT))
_otp_verify_limit = Depends(rate_limit("otp_verify", settings.OTP_VERIFY_RATE_LIMIT))
_otp_resend_limit = Depends(rate_limit("otp_resend", settings.OTP_RESEND_RATE_LIMIT))


def _auth_response(user: User) -> AuthResponse:
    return AuthResponse(token=create_access_token(user.id), user=UserOut.model_validate(user))


async def _send(sender: EmailSender, to: str, rendered: tmpl.RenderedEmail) -> None:
    try:
        await sender.send(
            to=to, subject=rendered.subject, html=rendered.html, text=rendered.text
        )
    except Exception:  # background task: never surface to the client
        pass


def _reset_url(raw_token: str) -> str:
    return oauth.append_query(
        f"{settings.FRONTEND_BASE_URL}/reset-password", token=raw_token
    )


# --- Email / password ------------------------------------------------------
@router.post(
    "/register",
    response_model=RegisterResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[_register_limit],
)
async def register(
    payload: RegisterRequest,
    db: DbSession,
    background: BackgroundTasks,
    sender: SenderDep,
) -> RegisterResponse:
    """Creates the account unverified and emails a 6-digit code.

    No session token yet — sign-in is blocked until POST /auth/verify-otp.
    """
    user = await auth_service.register_user(db, payload)
    raw_otp = await auth_service.issue_otp(db, user)
    await db.commit()

    background.add_task(
        _send,
        sender,
        user.email,
        tmpl.email_otp(
            first_name=user.first_name,
            code=raw_otp,
            ttl_minutes=settings.OTP_TTL_SECONDS // 60,
        ),
    )
    return RegisterResponse(
        message="Account created. Check your email for a verification code.",
        email=user.email,
        expires_in_seconds=settings.OTP_TTL_SECONDS,
    )


def _ip(request: Request) -> str | None:
    return request.client.host if request.client else None


@router.post("/verify-otp", response_model=AuthResponse, dependencies=[_otp_verify_limit])
async def verify_otp(
    payload: VerifyOtpRequest, db: DbSession, request: Request
) -> AuthResponse:
    user = await auth_service.verify_otp(db, payload.email, payload.code)
    await auth_service.record_login(db, user, method="password", ip=_ip(request))
    await db.commit()
    return _auth_response(user)


@router.post(
    "/resend-otp",
    response_model=MessageResponse,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[_otp_resend_limit],
)
async def resend_otp(
    payload: ResendOtpRequest, db: DbSession, background: BackgroundTasks, sender: SenderDep
) -> MessageResponse:
    result = await auth_service.resend_otp(db, payload.email)
    if result:
        user, raw_otp = result
        await db.commit()
        background.add_task(
            _send,
            sender,
            user.email,
            tmpl.email_otp(
                first_name=user.first_name,
                code=raw_otp,
                ttl_minutes=settings.OTP_TTL_SECONDS // 60,
            ),
        )
    return MessageResponse(
        message="If that account needs verifying, a new code is on its way."
    )


@router.post("/login", response_model=AuthResponse, dependencies=[_login_limit])
async def login(payload: LoginRequest, db: DbSession, request: Request) -> AuthResponse:
    user = await auth_service.authenticate_user(db, payload.email, payload.password)
    await auth_service.record_login(db, user, method="password", ip=_ip(request))
    await db.commit()
    return _auth_response(user)


@router.post("/refresh", response_model=AuthResponse)
async def refresh(
    db: DbSession, user: CurrentUser, claims: TokenClaims, request: Request
) -> AuthResponse:
    """Exchange a still-valid token for a fresh one; the old token is revoked."""
    await auth_service.revoke_token(
        db, claims["jti"], datetime.fromtimestamp(claims["exp"], tz=UTC)
    )
    await auth_service.record_login(db, user, method="refresh", ip=_ip(request))
    await db.commit()
    return _auth_response(user)


@router.post("/logout", response_model=MessageResponse)
async def logout(
    db: DbSession,
    _user: CurrentUser,
    creds: Annotated[HTTPAuthorizationCredentials, Depends(_bearer)],
) -> MessageResponse:
    try:
        claims = decode_access_token(creds.credentials)
        await auth_service.revoke_token(
            db, claims["jti"], datetime.fromtimestamp(claims["exp"], tz=UTC)
        )
        await db.commit()
    except jwt.PyJWTError:
        pass
    return MessageResponse(message="Signed out.")


@router.get("/me", response_model=UserOut)
async def me(user: CurrentUser) -> UserOut:
    return UserOut.model_validate(user)


@router.post(
    "/forgot-password",
    response_model=MessageResponse,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[_forgot_limit],
)
async def forgot_password(
    payload: ForgotPasswordRequest, db: DbSession, background: BackgroundTasks, sender: SenderDep
) -> MessageResponse:
    user = await auth_service.get_user_by_email(db, payload.email)
    if user and user.hashed_password:
        raw_token = await auth_service.issue_password_reset_token(db, user)
        await db.commit()
        background.add_task(
            _send,
            sender,
            user.email,
            tmpl.password_reset(first_name=user.first_name, reset_url=_reset_url(raw_token)),
        )
    return MessageResponse(
        message="If an account exists for that email, a reset link is on its way."
    )


@router.post("/reset-password", response_model=MessageResponse)
async def reset_password_endpoint(
    payload: ResetPasswordRequest, db: DbSession
) -> MessageResponse:
    await auth_service.reset_password(db, payload.token, payload.password)
    await db.commit()
    return MessageResponse(message="Password updated. You can now sign in.")


# --- Google OAuth --------------------------------------------------------------
@router.get("/google")
async def google_start(
    db: DbSession,
    redirect_uri: str = Query(default=None),
) -> RedirectResponse:
    if not settings.google_configured:
        raise OAuthNotConfigured("Google")
    target = oauth.validate_frontend_redirect(redirect_uri or f"{settings.FRONTEND_BASE_URL}/")
    state, challenge = await oauth.create_state(db, provider="google", redirect_uri=target)
    await db.commit()
    return RedirectResponse(
        oauth.google_authorize_url(state=state, code_challenge=challenge), status_code=307
    )


@router.get("/google/callback")
async def google_callback(
    db: DbSession,
    request: Request,
    state: str = Query(...),
    code: str | None = Query(default=None),
    error: str | None = Query(default=None),
) -> RedirectResponse:
    flow = await oauth.consume_state(db, provider="google", state=state)
    await db.commit()

    if error or not code:
        return RedirectResponse(
            oauth.append_query(flow.redirect_uri, error="oauth_denied"), status_code=302
        )
    try:
        profile = await oauth.google_fetch_profile(code=code, code_verifier=flow.code_verifier)
        user = await auth_service.upsert_oauth_user(db, provider="google", **profile)
        await auth_service.record_login(db, user, method="google", ip=_ip(request))
        await db.commit()
    except AppError:
        return RedirectResponse(
            oauth.append_query(flow.redirect_uri, error="oauth_failed"), status_code=302
        )
    return RedirectResponse(
        oauth.append_query(flow.redirect_uri, token=create_access_token(user.id)),
        status_code=302,
    )


# --- Apple OAuth ------------------------------------------------------------
@router.get("/apple")
async def apple_start(
    db: DbSession, redirect_uri: str = Query(default=None)
) -> RedirectResponse:
    if not settings.apple_configured:
        raise OAuthNotConfigured("Apple")
    target = oauth.validate_frontend_redirect(redirect_uri or f"{settings.FRONTEND_BASE_URL}/")
    state, _challenge = await oauth.create_state(db, provider="apple", redirect_uri=target)
    await db.commit()
    return RedirectResponse(oauth.apple_authorize_url(state=state), status_code=307)


@router.post("/apple/callback")
async def apple_callback(
    db: DbSession,
    request: Request,
    state: str = Form(...),
    code: str | None = Form(default=None),
    error: str | None = Form(default=None),
) -> RedirectResponse:
    flow = await oauth.consume_state(db, provider="apple", state=state)
    await db.commit()

    if error or not code:
        return RedirectResponse(
            oauth.append_query(flow.redirect_uri, error="oauth_denied"), status_code=302
        )
    try:
        profile = await oauth.apple_fetch_profile(code=code)
        user = await auth_service.upsert_oauth_user(db, provider="apple", **profile)
        await auth_service.record_login(db, user, method="apple", ip=_ip(request))
        await db.commit()
    except AppError:
        return RedirectResponse(
            oauth.append_query(flow.redirect_uri, error="oauth_failed"), status_code=302
        )
    return RedirectResponse(
        oauth.append_query(flow.redirect_uri, token=create_access_token(user.id)),
        status_code=302,
    )
