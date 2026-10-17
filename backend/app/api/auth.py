from datetime import datetime, timedelta, timezone
from typing import Annotated
import uuid

import jwt
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, EmailStr, Field
from pwdlib import PasswordHash
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.database import get_db
from app.db.models import User

router = APIRouter(prefix="/api/auth", tags=["Authentication"])
password_hash = PasswordHash.recommended()
bearer_scheme = HTTPBearer()


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=200)


class UserCreate(BaseModel):
    full_name: str = Field(min_length=1, max_length=150)
    email: EmailStr
    password: str = Field(min_length=12, max_length=200)


class UserResponse(BaseModel):
    user_id: uuid.UUID
    full_name: str
    email: str
    role: str
    is_active: bool

    model_config = {"from_attributes": True}


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    user: UserResponse


def get_current_user(
        credentials: Annotated[HTTPAuthorizationCredentials, Depends(bearer_scheme)],
        db: Session = Depends(get_db),
) -> User:
    unauthorized = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or expired access token",
        headers={"WWW-Authenticate": "Bearer"},
    )

    try:
        payload = jwt.decode(
            credentials.credentials,
            settings.jwt_secret_key,
            algorithms=[settings.jwt_algorithm],
        )
        subject = payload.get("sub")
        if not subject:
            raise unauthorized
        user_id = uuid.UUID(subject)
    except (jwt.InvalidTokenError, ValueError, TypeError):
        raise unauthorized

    user = db.get(User, user_id)
    if not user or not user.is_active:
        raise unauthorized

    return user


def require_admin(
        current_user: Annotated[User, Depends(get_current_user)],
) -> User:
    if current_user.role != "ADMIN":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Administrator access required",
        )
    return current_user


@router.post("/login", response_model=TokenResponse)
def login(payload: LoginRequest, db: Session = Depends(get_db)):
    email = str(payload.email).strip().lower()
    user = db.scalar(select(User).where(User.email == email))

    if (
            not user
            or not user.is_active
            or not password_hash.verify(payload.password, user.password_hash)
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    expires_in = settings.access_token_expire_minutes * 60
    expires_at = datetime.now(timezone.utc) + timedelta(seconds=expires_in)
    token = jwt.encode(
        {
            "sub": str(user.user_id),
            "exp": expires_at,
            "iat": datetime.now(timezone.utc),
        },
        settings.jwt_secret_key,
        algorithm=settings.jwt_algorithm,
    )

    return {
        "access_token": token,
        "token_type": "bearer",
        "expires_in": expires_in,
        "user": user,
    }


@router.get("/me", response_model=UserResponse)
def get_me(current_user: Annotated[User, Depends(get_current_user)]):
    return current_user


@router.post("/users", response_model=UserResponse, status_code=201)
def create_staff_user(
        payload: UserCreate,
        db: Session = Depends(get_db),
        admin: User = Depends(require_admin),
):
    email = str(payload.email).strip().lower()

    existing = db.scalar(select(User).where(User.email == email))
    if existing:
        raise HTTPException(status_code=409, detail="Email already exists")

    user = User(
        full_name=payload.full_name.strip(),
        email=email,
        password_hash=password_hash.hash(payload.password),
        role="STAFF",
        is_active=True,
    )
    db.add(user)

    try:
        db.commit()
        db.refresh(user)
    except Exception:
        db.rollback()
        raise

    return user