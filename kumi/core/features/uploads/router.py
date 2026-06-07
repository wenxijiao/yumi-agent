"""File upload routes."""

from __future__ import annotations

from fastapi import APIRouter
from kumi.core.features.uploads.service import decode_upload_payload, save_uploaded_file
from kumi.core.platform.http.dependencies import CurrentIdentity
from kumi.core.platform.http.schemas import FileUploadRequest
from kumi.core.platform.plugins import get_session_scope

router = APIRouter()


@router.post("/uploads")
async def uploads_endpoint(identity: CurrentIdentity, request: FileUploadRequest):
    raw = decode_upload_payload(request.content_base64)
    sid = get_session_scope().qualify_session_http(identity, request.session_id)
    return save_uploaded_file(
        sid,
        request.filename,
        raw,
        owner_user_id=identity.user_id if identity.user_id != "_local" else None,
    )
