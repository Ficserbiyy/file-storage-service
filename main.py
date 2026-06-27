from fastapi import FastAPI

from typing import Final



async def lifespan(app: FastAPI):
    
    
    
    
    yield
    
    

app: Final = FastAPI(title="File Storage", lifespan=lifespan)



