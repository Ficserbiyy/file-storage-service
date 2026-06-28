from fastapi import APIRouter, Depends, HTTPException, UploadFile
from config import User, UserFile, DownloadUrl
from sqlmodel.ext.asyncio.session import AsyncSession
from database import get_session, minio_client, MINIO_BUCKET_NAME
from auth import get_current_user
from io import BytesIO
from uuid import uuid4
from datetime import timedelta
from sqlmodel import select
from typing import Final


router: Final = APIRouter(prefix="/files", tags=["Files"])



@router.post("/upload", response_model=UserFile)
async def upload_file(
    file: UploadFile,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session)
):
    ''' Upload a file '''
    assert current_user.id is not None, "User.id can not be None"
    
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



@router.get("/{file_id}", response_model=DownloadUrl)
async def get_single_file(
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

