from sqlmodel import SQLModel, Field, Relationship, Column, DateTime
from datetime import datetime, timezone
from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Final


class UserBase(SQLModel):
    ''' For User creation '''
    email: str = Field(unique=True, index=True)

class User(UserBase, table=True):
    ''' User model '''
    id: int | None = Field(primary_key=True, default=None)
    is_active: bool = True
    hashed_password: str
    files: list["UserFile"] = Relationship(back_populates="user")

class FileCreate(SQLModel):
    filename: str
    content_type: str
    
class UserFile(FileCreate, table=True):
    id: int | None = Field(primary_key=True, default=None)
    owner_id: int = Field(foreign_key="user.id")
    storage_key: str
    size: int
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    
class UserCreate(UserBase):
    ''' For User registration '''
    password: str = Field(min_length=6)

class Settings(BaseSettings):
    ''' Enviroment Settings '''
    DB_USER: str = "postgres"
    DB_PASSWORD: str = "password"
    DB_HOST: str = "db" 
    DB_NAME: str = "storage"
    REDIS_URL: str = 'redis://redis:6379'
    MINIO_ENDPOINT: str = "localhost:9000"
    MINIO_ACCESS_KEY: str = "admin"
    MINIO_PASSWORD: str = "password"
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
