from __future__ import annotations

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException


class AppError(Exception):
    """Domain error mapped to a structured JSON envelope."""

    headers: dict[str, str] | None = None

    def __init__(self, status_code: int, code: str, message: str):
        self.status_code = status_code
        self.code = code
        self.message = message
        super().__init__(message)


class EmailAlreadyExists(AppError):
    def __init__(self) -> None:
        super().__init__(409, "email_exists", "An account with this email already exists.")


class InvalidCredentials(AppError):
    def __init__(self) -> None:
        super().__init__(401, "invalid_credentials", "Incorrect email or password.")


class InvalidToken(AppError):
    def __init__(self, message: str = "This link is invalid or has expired.") -> None:
        super().__init__(400, "invalid_token", message)


class OAuthNotConfigured(AppError):
    def __init__(self, provider: str) -> None:
        super().__init__(503, "oauth_not_configured", f"{provider} sign-in is not configured.")


class OAuthFailed(AppError):
    def __init__(self, message: str = "Social sign-in failed. Please try again.") -> None:
        super().__init__(400, "oauth_failed", message)


def _envelope(
    status_code: int,
    code: str,
    message: str,
    extra: dict | None = None,
    headers: dict | None = None,
) -> JSONResponse:
    body: dict = {"error": {"code": code, "message": message}}
    if extra:
        body["error"].update(extra)
    return JSONResponse(status_code=status_code, content=body, headers=headers)


def register_exception_handlers(app) -> None:
    @app.exception_handler(AppError)
    async def _app_error(_: Request, exc: AppError) -> JSONResponse:
        return _envelope(exc.status_code, exc.code, exc.message, headers=exc.headers)

    @app.exception_handler(RequestValidationError)
    async def _validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        fields = [
            {"field": ".".join(str(p) for p in e["loc"] if p not in ("body",)), "message": e["msg"]}
            for e in exc.errors()
        ]
        return _envelope(422, "validation_error", "Some fields are invalid.", {"fields": fields})

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = {401: "unauthorized", 403: "forbidden", 404: "not_found"}.get(
            exc.status_code, "http_error"
        )
        detail = exc.detail if isinstance(exc.detail, str) else "Request failed."
        return _envelope(exc.status_code, code, detail)
