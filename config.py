from sqlmodel import SQLModel, Field, Relationship, Column, DateTime
from datetime import datetime, timezone
from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Final


class UserBase(SQLModel):
    ''' For User creation '''
    email: str = Field(unique=True, index=True)

class UserCreate(UserBase):
    ''' For User registration '''
    password: str = Field(min_length=6)

class User(UserBase, table=True):
    ''' User model '''
    id: int | None = Field(primary_key=True, default=None)
    is_active: bool = True
    hashed_password: str
    files: list["UserFile"] = Relationship(back_populates="user")

class UserFile(SQLModel, table=True):
    id: int | None = Field(primary_key=True, default=None)
    owner_id: int = Field(foreign_key="user.id")
    filename: str
    current_version: int = 1
    created_at: datetime = Field(sa_column=Column(DateTime(timezone=True), nullable=False), default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(sa_column=Column(DateTime(timezone=True), nullable=False), default_factory=lambda: datetime.now(timezone.utc))
    deleted_at: datetime | None = Field(default=None, sa_column=Column(DateTime(timezone=True), nullable=True))
    user: "User" = Relationship(back_populates="files")
    versions: list["FileVersion"] = Relationship(back_populates="userfile")

class FileVersion(SQLModel, table=True):
    ''' Actual User File '''
    id: int | None = Field(default=None, primary_key=True)
    file_id: int = Field(foreign_key="userfile.id")
    version: int
    storage_key: str
    size: int
    content_type: str
    created_at: datetime = Field(sa_column=Column(DateTime(timezone=True), nullable=False), default_factory=lambda: datetime.now(timezone.utc))
    userfile: UserFile | None = Relationship(back_populates="versions")

class FileRead(SQLModel):
    id: int
    filename: str
    current_version: int
    created_at: datetime
    updated_at: datetime

class DownloadUrl(SQLModel):
    url: str

class ShareFileCreate(SQLModel):
    expires_in_days: int | None = Field(default=None, ge=1, le=365)
    max_downloads: int | None = Field(default=None, ge=1, le=1000)

class SharedLink(SQLModel, table=True):
    id: int | None = Field(primary_key=True, default=None)
    file_id: int = Field(foreign_key="userfile.id", unique=True)
    token: str = Field(index=True, unique=True)
    created_at: datetime = Field(sa_column=Column(DateTime(timezone=True), nullable=False), default_factory=lambda: datetime.now(timezone.utc))
    expires_at: datetime | None = Field(sa_column=Column(DateTime(timezone=True), nullable=True))
    download_count: int = 0
    max_downloads: int | None = None
    file: "UserFile" = Relationship()

class Settings(BaseSettings):
    ''' Enviroment Settings '''
    DB_USER: str = "postgres"
    DB_PASSWORD: str = "password"
    DB_HOST: str = "db" 
    DB_NAME: str = "storage"
    REDIS_URL: str = 'redis://redis:6379'
    MINIO_ENDPOINT: str = "minio:9000"
    MINIO_ROOT_USER: str = "admin"
    MINIO_ROOT_PASSWORD: str = "password"
    MINIO_BUCKET_NAME: str = "user-files"
    SECRET_KEY: str = " "
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRE: int = 30
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding='utf-8',
        extra='ignore',
        case_sensitive=False
    )
    @property
    def DATABASE_URL(self) -> str:
        return f"postgresql+asyncpg://{self.DB_USER}:{self.DB_PASSWORD}@{self.DB_HOST}/{self.DB_NAME}"


settings: Final = Settings()
