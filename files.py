from fastapi import APIRouter, Depends, HTTPException, UploadFile, Response, Request, Query
from fastapi.encoders import jsonable_encoder
from fastapi.responses import StreamingResponse
from sqlmodel import select, col, and_, func
from config import User, DownloadUrl, UserFile, FileRead, FileVersion, SharedLink, ShareFileCreate
from sqlmodel.ext.asyncio.session import AsyncSession
from database import get_session, minio_client, MINIO_BUCKET_NAME, redis_client, MAX_STORAGE_BYTES
from auth import get_current_user
from io import BytesIO
from uuid import uuid4
from datetime import timedelta, datetime, timezone
from json import dumps, loads as json_loads
from hashlib import sha256 as hashlib_sha256
from secrets import token_urlsafe
from math import ceil
from typing import Final
from fileversions import (get_file_by_id, get_file_by_url, get_deleted_file, get_used_storage,
    get_current_file_version, get_certain_file_version, set_api_rate_limit, validate_storage_quota)


router: Final = APIRouter(prefix="/files", tags=["Files"])


@router.post("/upload", status_code=201)
async def upload_file(
    file: UploadFile,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session)
):
    ''' Upload a file '''
    assert current_user.id is not None, "User ID can not be None"
    
    storage_key = (f"users/{current_user.id}/{uuid4()}-{file.filename}")
    contents = await file.read()
    size = len(contents)
    await validate_storage_quota(size, current_user, session)
    
    minio_client.put_object(
    bucket_name=MINIO_BUCKET_NAME,
    object_name=storage_key,
    data=BytesIO(contents),
    length=size,
    part_size=10 * 1024 * 1024,
    )
    
    
    db_file = UserFile(
    filename=file.filename or "unknown",
    owner_id=current_user.id,
    )
    session.add(db_file)
    await session.flush()
    assert db_file.id is not None, "File ID can not be None"
    
    
    db_version = FileVersion(
    file_id=db_file.id,
    version=1,
    storage_key=storage_key,
    content_type=file.content_type or "application/octet-stream",
    size=size,
    )
    session.add(db_version)
    await session.commit()
    await session.refresh(db_file)
    await session.refresh(db_version)
    return db_file



@router.get("/storage", status_code=200)
async def get_storage_statistics(
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session)
):
    ''' Receive user storage statistics '''
    
    used_bytes = await get_used_storage(current_user, session)
    response = {
        "used_bytes": used_bytes,
        "used_mb": round(used_bytes / (1024 * 1024), 2),
        "quota_bytes": MAX_STORAGE_BYTES,
        "quota_gb": round(MAX_STORAGE_BYTES / (1024 ** 3), 2),
        "used_percent": round((used_bytes / MAX_STORAGE_BYTES) * 100, 2),
        "remaining_bytes": MAX_STORAGE_BYTES - used_bytes
    }
    return response



@router.post("/{file_id}/share")
async def share_file(
    file_id: int,
    share_in: ShareFileCreate,
    request: Request,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session)    
):
    ''' Create URL for sharing a file '''
    
    client_ip = request.client.host if request.client else "127.0.0.1"
    limit_key = f"limit:shortcodes:{client_ip}"
    await set_api_rate_limit(limit_key)


    statement = select(SharedLink).where(SharedLink.file_id == file_id)
    result = await session.exec(statement)
    existing_link = result.one_or_none()
    if existing_link:
        return {"share_url":f"http://localhost:8000/files/shared/{existing_link.token}"}
    
    db_file = await get_file_by_id(file_id, current_user, session)
    token = token_urlsafe(32)
    assert db_file.id is not None 
    expires_at = None

    if share_in.expires_in_days is not None:
        expires_at = (
            datetime.now(timezone.utc)
            + timedelta(days=share_in.expires_in_days)
        )

    shared_link = SharedLink(
        file_id=db_file.id,
        token=token,
        expires_at=expires_at,
        max_downloads=share_in.max_downloads
    )
    session.add(shared_link)
    await session.commit()
    await session.refresh(shared_link)
    return {"share_url": f"http://localhost:8000/files/shared/{token}"}



@router.get("/shared/{token}")
async def get_shared_file(
    token: str,
    session: AsyncSession = Depends(get_session),
):
    ''' Receive shared file using the URL '''

    shared_file = await get_file_by_url(token, session)
    
    if shared_file.expires_at is not None and shared_file.expires_at < datetime.now(timezone.utc):
        raise HTTPException(status_code=400, detail="URL expired")
    if shared_file.max_downloads is not None and shared_file.download_count >= shared_file.max_downloads:
        raise HTTPException(status_code=400, detail="Download limit exceeded")
    
    current_file_version = await get_current_file_version(session, shared_file.file)
    shared_file.download_count += 1
    await session.commit()

    obj = minio_client.get_object(MINIO_BUCKET_NAME, current_file_version.storage_key)
    return StreamingResponse(
        obj,
        media_type=current_file_version.content_type,
        headers={"Content-Disposition": f'attachment; filename="{shared_file.file.filename}"'}
    )



@router.get("/")
async def get_user_files(
    request: Request,
    response: Response,
    search_filename: str | None = None,
    sort_by: str | None = None,
    page: int = Query(1, ge=1),
    limit: int = Query(10, ge=1, le=100),
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user)
):
    ''' Receive all files belonging to the current user '''
    
    base_statement = select(UserFile).where(UserFile.owner_id == current_user.id, col(UserFile.deleted_at).is_(None),)
    filters = []
    
    if search_filename:
        filters.append(col(UserFile.filename).ilike(f"%{search_filename}%"))

    if filters:
        base_statement = base_statement.where(and_(*filters))


    match sort_by:
        case "date_asc":
            statement = base_statement.order_by(col(UserFile.created_at))
        case "date_desc":
            statement = base_statement.order_by(col(UserFile.created_at).desc())
        case "id_desc":
            statement = base_statement.order_by(col(UserFile.id).desc())
        case _:
            statement = base_statement.order_by(col(UserFile.id))
        
        
    statement = statement.offset((page - 1) * limit).limit(limit)
    result = await session.exec(statement)
    files = result.all()
            
    count_statement = (select(func.count()).select_from(base_statement.subquery()))
    total = await session.scalar(count_statement) or 0
    pages = ceil(total / limit) if total else 1

    result_data = {
        "files": [FileRead.model_validate(file) for file in files],
        "page": page,
        "limit": limit,
        "total": total,
        "pages": pages,
        "has_next_page": page < pages,
        "has_prev_page": page > 1,
    }
    
    
    json_bytes = dumps(jsonable_encoder(result_data), sort_keys=True).encode("utf-8")
    generated_etag = f'W/"{hashlib_sha256(json_bytes).hexdigest()}"'
    
    client_etag = request.headers.get("If-None-Match")
    if client_etag == generated_etag:
        return Response(status_code=304)
        
    response.headers["ETag"] = generated_etag
    response.headers["Cache-Control"] = "no-cache"
    return result_data    



@router.get("/trash", status_code=200)
async def get_trashed_files(
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    ''' Receive trashed files '''
    
    cache_key = f"trashed_files:user:{current_user.id}"
    cached_data = await redis_client.get(cache_key)
    if cached_data:
        return json_loads(cached_data)
    
    statement = select(UserFile).where(UserFile.owner_id == current_user.id, col(UserFile.deleted_at).is_not(None))
    result = await session.exec(statement)
    files = result.all()
    
    await redis_client.set(cache_key, dumps(jsonable_encoder(files)), ex=600)
    return files



@router.get("/{file_id}/versions")
async def get_all_file_versions(
    file_id: int,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session)
):
    ''' Get all file versions '''
    
    cache_key = f"file_versions:user:{current_user.id}:file:{file_id}"
    cached_data = await redis_client.get(cache_key)
    if cached_data:
        return json_loads(cached_data)
    
    db_file = await get_file_by_id(file_id, current_user, session)
    statement = select(FileVersion).where(FileVersion.file_id == db_file.id)  
    result = await session.exec(statement)
    versions = result.all()
    
    response = [FileVersion.model_validate(version) for version in versions]
    await redis_client.set(cache_key, dumps(jsonable_encoder(response)), ex=600)
    return response



@router.get("/{file_id}", response_model=DownloadUrl)
async def get_file_signed_url(
    file_id: int,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session)    
):
    ''' Receive a signed URL by file id '''
    db_file = await get_file_by_id(file_id, current_user, session)
    current_version = await get_current_file_version(session, db_file)
    
    url = minio_client.presigned_get_object(
    MINIO_BUCKET_NAME,
    current_version.storage_key,
    expires=timedelta(minutes=10),
    )
    return DownloadUrl(url=url)



@router.get("/{file_id}/download")
async def download_single_file(
    file_id: int,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session)  
):
    ''' Actually download the file '''
    db_file = await get_file_by_id(file_id, current_user, session)
    current_version = await get_current_file_version(session, db_file)
    
    try:
        obj = minio_client.get_object(MINIO_BUCKET_NAME, current_version.storage_key)
        return StreamingResponse(
            obj,
            media_type=current_version.content_type,
            headers={"Content-Disposition": f'attachment; filename="{db_file.filename}"'}
        )
    except Exception as e:
        print(type(e), e)
        raise HTTPException(status_code=404, detail="File not found in storage")



@router.get("/{file_id}/versions/{version_in}/download")
async def download_old_version(
    file_id: int,
    version_in: int,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session) 
):
    ''' Download certain versions of the file '''
    
    db_file = await get_file_by_id(file_id, current_user, session)
    old_file_version = await get_certain_file_version(file_id, version_in, session)
    
    try:
        obj = minio_client.get_object(MINIO_BUCKET_NAME, old_file_version.storage_key)
        return StreamingResponse(
            obj,
            media_type=old_file_version.content_type,
            headers={"Content-Disposition": f'attachment; filename="{db_file.filename}"'}
        )
    except Exception as e:
        print(type(e), e)
        raise HTTPException(status_code=404, detail="File not found in storage")



@router.put("/{file_id}", response_model=FileVersion)
async def update_user_file(
    file_id: int,
    file_in: UploadFile,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session)
):
    ''' Update the user file '''
    db_file = await get_file_by_id(file_id, current_user, session)
    new_version = db_file.current_version + 1
    
    contents = await file_in.read()
    size = len(contents)
    assert db_file.id is not None, "File ID can not be None"
    
    storage_key = (
    f"users/{current_user.id}/"
    f"{db_file.id}/"
    f"v{new_version}-"
    f"{uuid4()}-{file_in.filename}"
    )
    minio_client.put_object(
    bucket_name=MINIO_BUCKET_NAME,
    object_name=storage_key,
    data=BytesIO(contents),
    length=size,
    part_size=10 * 1024 * 1024,
    )
    
    db_version = FileVersion(
    file_id=db_file.id,
    version=new_version,
    storage_key=storage_key,
    content_type=file_in.content_type or "application/octet-stream",
    size=size,
    )
    db_file.current_version = new_version
    db_file.updated_at = datetime.now(timezone.utc)
    
    session.add(db_version)
    await session.commit()
    await session.refresh(db_version)
    
    await redis_client.delete(f"file_versions:user:{current_user.id}:file:{file_id}")
    return db_version



@router.delete("/{file_id}", status_code=200)
async def delete_single_file(
    file_id: int,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session) 
):
    ''' Delete the user file by its id '''
    
    db_file = await get_file_by_id(file_id, current_user, session)
    db_file.deleted_at = datetime.now(timezone.utc)
    await session.commit()
    await session.refresh(db_file)
    
    await redis_client.delete(f"file_versions:user:{current_user.id}:file:{file_id}")
    return {"detail": "File moved to trash"}



@router.post("/{file_id}/restore", status_code=200)
async def restore_file(
    file_id: int,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    ''' Restore trashed file '''

    db_file = await get_deleted_file(file_id, current_user, session)
    db_file.deleted_at = None
    await session.commit()
    
    await redis_client.delete(f"trashed_files:user:{current_user.id}")
    return {"detail": "File restored"}
