import mimetypes
import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, status

from app.core.security import get_current_user
from app.schemas.auth import CurrentUser
from app.services.realtime import get_supabase_client

BUCKET = "chat-media"
MAX_FILE_SIZE = 100 * 1024 * 1024  # 100 MB

router = APIRouter(prefix="/api/v1/chat/media", tags=["chat-media"])


@router.post("/upload")
async def upload_media(
    file: UploadFile = File(...),
    current_user: CurrentUser = Depends(get_current_user),
):
    data = await file.read()

    if len(data) > MAX_FILE_SIZE:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"File troppo grande (max {MAX_FILE_SIZE // 1024 // 1024} MB)",
        )

    mime_type = file.content_type or "application/octet-stream"
    ext = mimetypes.guess_extension(mime_type) or ""
    # Prefer the original extension if available
    if file.filename and "." in file.filename:
        ext = "." + file.filename.rsplit(".", 1)[-1].lower()

    timestamp = int(datetime.utcnow().timestamp() * 1000)
    random_suffix = uuid.uuid4().hex[:10]
    path = f"{current_user.user_id}/{timestamp}-{random_suffix}{ext}"

    client = get_supabase_client()
    try:
        client.storage.from_(BUCKET).upload(
            path=path,
            file=data,
            file_options={"content-type": mime_type, "upsert": False},
        )
    except Exception as exc:
        err_str = str(exc).lower()
        if "duplicate" in err_str or "already exists" in err_str:
            raise HTTPException(status_code=409, detail="File già esistente")
        raise HTTPException(status_code=502, detail=f"Errore upload storage: {exc}")

    public_url = client.storage.from_(BUCKET).get_public_url(path)

    return {
        "url": public_url,
        "file_name": file.filename or f"file{ext}",
        "file_size": len(data),
        "mime_type": mime_type,
    }
