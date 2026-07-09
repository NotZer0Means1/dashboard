from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.schemas import LoginRequest, TokenResponse, UserCreate, UserOut
from app.security import create_access_token
from app.services import user_service

router = APIRouter(tags=["auth"])


@router.post("/auth", response_model=UserOut, status_code=status.HTTP_201_CREATED)
def register(payload: UserCreate, db: Session = Depends(get_db)) -> UserOut:
    return user_service.create_user(db, payload.login, payload.password)


@router.post("/login", response_model=TokenResponse)
def login(payload: LoginRequest, db: Session = Depends(get_db)) -> TokenResponse:
    user = user_service.authenticate_user(db, payload.login, payload.password)
    return TokenResponse(access_token=create_access_token(subject=user.login))
