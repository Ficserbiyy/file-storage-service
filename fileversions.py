from fastapi import HTTPException
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession
from config import UserFile, FileVersion, User


async def get_user_file(
    file_id: int,
    current_user: User,
    session: AsyncSession,
) -> UserFile:
    
    statement = select(UserFile).where(
        UserFile.id == file_id,
        UserFile.owner_id == current_user.id,
    )
    result = await session.exec(statement)
    db_file = result.one_or_none()
    
    if not db_file:
        raise HTTPException(status_code=404, detail="File not found")
    return db_file


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
