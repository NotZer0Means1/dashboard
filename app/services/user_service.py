from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.models import User
from app.security import hash_password, verify_password


def get_user_by_login(db: Session, login: str) -> User | None:
    return db.query(User).filter(User.login == login).first()


def create_user(db: Session, login: str, password: str) -> User:
    if get_user_by_login(db, login) is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Login already taken")

    user = User(login=login, hashed_password=hash_password(password))
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def authenticate_user(db: Session, login: str, password: str) -> User:
    user = get_user_by_login(db, login)
    if user is None or not verify_password(password, user.hashed_password):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid login or password")
    return user
