from fastapi import APIRouter, Depends, HTTPException, UploadFile, Response, Request, Query
from fastapi.encoders import jsonable_encoder
from fastapi.responses import StreamingResponse
from sqlmodel import select, col, and_, func
from config import User, UserFile, FileRead, DownloadUrl
from sqlmodel.ext.asyncio.session import AsyncSession
from database import get_session, minio_client, MINIO_BUCKET_NAME
from auth import get_current_user
from io import BytesIO
from uuid import uuid4
from datetime import timedelta
from json import dumps
from hashlib import sha256 as hashlib_sha256
from math import ceil
from typing import Final


router: Final = APIRouter(prefix="/files", tags=["Files"])



@router.post("/upload", response_model=UserFile)
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
    storage_key=storage_key,
    content_type=file.content_type or "application/octet-stream",
    size=size,
    )
    
    session.add(db_file)
    await session.commit()
    await session.refresh(db_file)
    return db_file



@router.get("/")
async def get_user_files(
    request: Request,
    response: Response,
    search_filename: str | None = None,
    search_content_type: str | None = None,
    sort_by: str | None = None,
    page: int = Query(1, ge=1),
    limit: int = Query(10, ge=1, le=100),
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user)
):
    ''' Receive all files belonging to the current user '''
    
    base_statement = select(UserFile).where(UserFile.owner_id == current_user.id)
    filters = []
    
    if search_filename:
        filters.append(col(UserFile.filename).ilike(f"%{search_filename}%"))

    if search_content_type:
        filters.append(col(UserFile.content_type).ilike(f"%{search_content_type}%"))

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



@router.get("/{file_id}", response_model=DownloadUrl)
async def get_single_file_url(
    file_id: int,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session)    
):
    ''' Receive a signed URL by file id '''
    statement = select(UserFile).where(UserFile.id == file_id, UserFile.owner_id == current_user.id)
    result = await session.exec(statement)
    db_file = result.one_or_none()
    
    if not db_file:
        raise HTTPException(status_code=404, detail="File not found")
        
    url = minio_client.presigned_get_object(
    MINIO_BUCKET_NAME,
    db_file.storage_key,
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
    
    statement = select(UserFile).where(UserFile.id == file_id, UserFile.owner_id == current_user.id)
    result = await session.exec(statement)
    db_file = result.one_or_none()
    
    if not db_file:
        raise HTTPException(status_code=404, detail="File not found")
    try:
        obj = minio_client.get_object(MINIO_BUCKET_NAME, db_file.storage_key)
        return StreamingResponse(obj, media_type=db_file.content_type, headers={"Content-Disposition": f'attachment; filename="{db_file.filename}"'})
    
    except Exception:
        raise HTTPException(status_code=404, detail="File not found in storage")






@router.delete("/{file_id}", status_code=200)
async def delete_single_file(
    file_id: int,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session) 
):
    ''' Delete the user file by its id '''
    
    statement = select(UserFile).where(UserFile.id == file_id, UserFile.owner_id == current_user.id)
    result = await session.exec(statement)
    db_file = result.one_or_none()
    
    if not db_file:
        raise HTTPException(status_code=404, detail="File not found")
    
    minio_client.remove_object(MINIO_BUCKET_NAME, db_file.storage_key)
    await session.delete(db_file)
    await session.commit()
    return {"detail": "File successfully deleted"}
