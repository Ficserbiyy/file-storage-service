from fastapi import HTTPException
from sqlmodel import select, col, func
from sqlmodel.ext.asyncio.session import AsyncSession
from database import redis_client, MAX_STORAGE_BYTES
from config import UserFile, FileVersion, User, SharedLink


async def get_file_by_id(
    file_id: int,
    current_user: User,
    session: AsyncSession,
) -> UserFile:
    
    statement = select(UserFile).where(
        UserFile.id == file_id,
        UserFile.owner_id == current_user.id,
        col(UserFile.deleted_at).is_(None),
    )
    result = await session.exec(statement)
    db_file = result.one_or_none()
    
    if not db_file:
        raise HTTPException(
            status_code=404,
            detail="File not found"
        )
    return db_file


async def get_file_by_url(
    token: str,
    session: AsyncSession,    
) -> SharedLink:
    statement = select(SharedLink).where(
        SharedLink.token == token
    )
    result = await session.exec(statement)
    shared_file = result.one_or_none()
    
    if not shared_file:
        raise HTTPException(status_code=404, detail="File not found")
    return shared_file


async def get_current_file_version(
    session: AsyncSession,
    file: UserFile,
) -> FileVersion:
    
    statement = select(FileVersion).where(
        FileVersion.file_id == file.id,
        FileVersion.version == file.current_version,
    )
    result = await session.exec(statement)
    return result.one()


async def get_deleted_file(
    file_id: int,
    current_user: User,
    session: AsyncSession
) -> UserFile:
    statement = select(UserFile).where(
        UserFile.id == file_id,
        UserFile.owner_id == current_user.id,
        col(UserFile.deleted_at).is_not(None),
    )
    result = await session.exec(statement)
    db_file = result.one_or_none()
    if not db_file:
        raise HTTPException(
            status_code=404,
            detail="File not found in trash"
        )
    return db_file


async def get_certain_file_version(
    file_id: int,
    version_in: int,
    session: AsyncSession
) -> FileVersion:
    statement = select(FileVersion).where(
        FileVersion.file_id == file_id,
        FileVersion.version == version_in
    )
    result = await session.exec(statement)
    file_version = result.one_or_none()
    if file_version is None:
        raise HTTPException(
            status_code=404,
            detail="Version not found"
        )
    return file_version


async def get_used_storage(
    current_user: User,
    session: AsyncSession,
) -> int:
    statement = (
        select(func.sum(FileVersion.size))
        .join(UserFile)
        .where(
            UserFile.owner_id == current_user.id,
            col(UserFile.deleted_at).is_(None),
        )
    )
    used_storage = await session.scalar(statement)
    return used_storage or 0


async def validate_storage_quota(
    size: int,
    current_user: User,
    session: AsyncSession,
):
    used_storage = await get_used_storage(
        current_user,
        session,
    )
    if used_storage + size > MAX_STORAGE_BYTES:
        raise HTTPException(
            status_code=400,
            detail="Your storage quota has been exceeded",
        )


async def set_api_rate_limit(limit_key: str):
    current_count = await redis_client.incr(limit_key)
    
    if current_count == 1:
        await redis_client.expire(limit_key, 60)
    if current_count > 10:
        raise HTTPException(status_code=429, detail="Too Many Requests")