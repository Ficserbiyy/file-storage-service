from fastapi import HTTPException, status
from config import settings
from datetime import datetime, timedelta, timezone
from bcrypt import gensalt, hashpw, checkpw       
from jwt import encode as jwt_encode, decode as jwt_decode, PyJWTError        
        
        
def hash_password(password: str) -> str:
    ''' Securely hash a password using direct bcrypt library. '''
    
    pwd_bytes = password.encode('utf-8')
    if len(pwd_bytes) > 72:
        pwd_bytes = pwd_bytes[:72]
        
    salt = gensalt()
    hashed = hashpw(pwd_bytes, salt)
    return hashed.decode('utf-8')



def verify_password(plain_password: str, hashed_password: str) -> bool:
    ''' Verify password. '''
    try:
        return checkpw(
            plain_password.encode('utf-8'), 
            hashed_password.encode('utf-8')
        )
    except Exception:
        return False
    


def create_access_token(data: dict) -> str:
    ''' Generate a secure JWT token. '''
    
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + timedelta(minutes=15)
    to_encode.update({"exp": expire})
    
    encoded_jwt = jwt_encode(to_encode, settings.SECRET_KEY, algorithm=settings.JWT_ALGORITHM)
    return encoded_jwt



def decode_access_token(token: str) -> str:
    ''' Decode JWT token and return the username. '''
    try:
        payload = jwt_decode(token, settings.SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
        username: str | None = payload.get("sub")
        
        if username is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Could not validate credentials",
            )
        return username
    
    except PyJWTError as e:
        print(f"JWT Error detail: {e}") 
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Token validation failed: {str(e)}",
        )
