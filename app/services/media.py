from __future__ import annotations

import asyncio
import re
import time

import cloudinary
import cloudinary.api
import cloudinary.uploader
import cloudinary.utils

from app.core.config import settings
from app.core.exceptions import AppError

# transformation segments that can precede the version in a delivery URL
_TRANSFORM_RE = re.compile(r"^[a-z]{1,3}_[^/]+$|,")
_VERSION_RE = re.compile(r"^v\d+$")

_configured = False

ALLOWED_RESOURCE_TYPES = ("image", "video")
_MAX_BYTES = 25 * 1024 * 1024  # 25 MB per file


class MediaNotConfigured(AppError):
    def __init__(self) -> None:
        super().__init__(503, "media_not_configured", "Media uploads are not configured.")


class MediaError(AppError):
    def __init__(self, message: str = "Media operation failed.") -> None:
        super().__init__(502, "media_error", message)


def _ensure_configured() -> None:
    global _configured
    if not settings.cloudinary_configured:
        raise MediaNotConfigured()
    if not _configured:
        cloudinary.config(
            cloud_name=settings.CLOUDINARY_CLOUD_NAME,
            api_key=settings.CLOUDINARY_API_KEY,
            api_secret=settings.CLOUDINARY_API_SECRET,
            secure=True,
        )
        _configured = True


def _asset_from_result(res: dict) -> dict:
    return {
        "url": res["secure_url"],
        "public_id": res["public_id"],
        "resource_type": res.get("resource_type", "image"),
        "format": res.get("format"),
        "bytes": res.get("bytes"),
        "width": res.get("width"),
        "height": res.get("height"),
    }


def _upload_sync(data: bytes, *, resource_type: str) -> dict:
    return cloudinary.uploader.upload(
        data,
        folder=settings.CLOUDINARY_UPLOAD_FOLDER,
        resource_type=resource_type,
        overwrite=False,
        unique_filename=True,
    )


async def upload_bytes(data: bytes, *, resource_type: str = "image") -> dict:
    _ensure_configured()
    if resource_type not in ALLOWED_RESOURCE_TYPES:
        raise MediaError(f"resource_type must be one of {ALLOWED_RESOURCE_TYPES}")
    if len(data) > _MAX_BYTES:
        raise AppError(413, "file_too_large", "File exceeds the 25 MB limit.")
    try:
        res = await asyncio.to_thread(_upload_sync, data, resource_type=resource_type)
    except Exception as exc:  # cloudinary raises its own Error types
        raise MediaError(str(exc)) from exc
    return _asset_from_result(res)


async def destroy(public_id: str, *, resource_type: str = "image") -> bool:
    """Best-effort delete. Returns True on 'ok'/'not found', False otherwise."""
    _ensure_configured()
    try:
        res = await asyncio.to_thread(
            cloudinary.uploader.destroy, public_id, resource_type=resource_type
        )
    except Exception:
        return False
    return res.get("result") in ("ok", "not found")


async def list_assets(*, resource_type: str = "image") -> list[dict]:
    """Every asset under the configured folder (paged). [] if not configured."""
    if not settings.cloudinary_configured:
        return []
    _ensure_configured()
    prefix = settings.CLOUDINARY_UPLOAD_FOLDER
    out: list[dict] = []
    cursor: str | None = None
    while True:
        kwargs = {
            "type": "upload",
            "prefix": prefix,
            "resource_type": resource_type,
            "max_results": 500,
        }
        if cursor:
            kwargs["next_cursor"] = cursor
        try:
            page = await asyncio.to_thread(cloudinary.api.resources, **kwargs)
        except Exception:
            break
        out.extend(page.get("resources", []))
        cursor = page.get("next_cursor")
        if not cursor:
            break
    return out


def public_id_from_url(url: str | None) -> str | None:
    """Best-effort public_id for a res.cloudinary.com delivery URL."""
    if not url or "res.cloudinary.com" not in url:
        return None
    marker = "/upload/"
    idx = url.find(marker)
    if idx == -1:
        return None
    tail = url[idx + len(marker) :].split("?")[0]
    parts = [p for p in tail.split("/") if p]
    # drop leading transformation segments and the version segment
    while parts and (_VERSION_RE.match(parts[0]) or _TRANSFORM_RE.search(parts[0])):
        parts.pop(0)
    if not parts:
        return None
    last = parts[-1]
    if "." in last:
        parts[-1] = last.rsplit(".", 1)[0]
    return "/".join(parts) or None


def sign_upload(extra: dict | None = None) -> dict:
    """Params for a signed browser -> Cloudinary direct upload."""
    _ensure_configured()
    params = {"folder": settings.CLOUDINARY_UPLOAD_FOLDER, "timestamp": int(time.time())}
    if extra:
        params.update({k: v for k, v in extra.items() if v is not None})
    signature = cloudinary.utils.api_sign_request(params, settings.CLOUDINARY_API_SECRET)
    return {
        "cloud_name": settings.CLOUDINARY_CLOUD_NAME,
        "api_key": settings.CLOUDINARY_API_KEY,
        "signature": signature,
        **params,
    }
