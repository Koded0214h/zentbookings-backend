from __future__ import annotations

from app.schemas.common import CamelModel


class MediaAsset(CamelModel):
    url: str
    public_id: str
    resource_type: str
    format: str | None = None
    bytes: int | None = None
    width: int | None = None
    height: int | None = None


class UploadResponse(CamelModel):
    assets: list[MediaAsset]


class SignedUploadResponse(CamelModel):
    cloud_name: str
    api_key: str
    signature: str
    timestamp: int
    folder: str


class DeleteMediaRequest(CamelModel):
    public_id: str
    resource_type: str = "image"


class DeleteMediaResponse(CamelModel):
    deleted: bool
