from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, UploadFile

from app.api.deps import require_roles
from app.schemas.media import (
    DeleteMediaRequest,
    DeleteMediaResponse,
    MediaAsset,
    SignedUploadResponse,
    UploadResponse,
)
from app.services import media

router = APIRouter(prefix="/media", tags=["media"])

_staff_only = [Depends(require_roles("admin", "agent"))]


@router.post("/upload", response_model=UploadResponse, dependencies=_staff_only)
async def upload_media(
    files: Annotated[list[UploadFile], File()],
    resource_type: Annotated[str, Form()] = "image",
) -> UploadResponse:
    """Server-side upload: multipart file(s) -> Cloudinary -> asset URLs."""
    assets: list[MediaAsset] = []
    for f in files:
        data = await f.read()
        result = await media.upload_bytes(data, resource_type=resource_type)
        assets.append(MediaAsset.model_validate(result))
    return UploadResponse(assets=assets)


@router.post("/sign", response_model=SignedUploadResponse, dependencies=_staff_only)
async def sign_upload() -> SignedUploadResponse:
    """Params for a signed browser -> Cloudinary direct upload."""
    return SignedUploadResponse.model_validate(media.sign_upload())


@router.post("/delete", response_model=DeleteMediaResponse, dependencies=_staff_only)
async def delete_media(payload: DeleteMediaRequest) -> DeleteMediaResponse:
    ok = await media.destroy(payload.public_id, resource_type=payload.resource_type)
    return DeleteMediaResponse(deleted=ok)
