from fastapi import FastAPI
from database import engine, redis_client, minio_client, create_db_and_tables, MINIO_BUCKET_NAME
from contextlib import asynccontextmanager
from asyncio import sleep
from typing import Final

    
@asynccontextmanager
async def lifespan(app: FastAPI):
    
    if not minio_client.bucket_exists(MINIO_BUCKET_NAME):
        minio_client.make_bucket(MINIO_BUCKET_NAME)
        
    for attempt in range(10):
        try:
            print(f"Attempt {attempt + 1}")
            await create_db_and_tables()
            print("Connected!")
            break
        except Exception as e:
            print(type(e), e)
            await sleep(2)
    else:
        raise RuntimeError("Database never became available.")
    

    yield
    await engine.dispose()
    await redis_client.aclose()


app: Final = FastAPI(title="File Storage", lifespan=lifespan)



