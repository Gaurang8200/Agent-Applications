from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.config import get_settings
from app.core.security import create_access_token, hash_password, verify_password
from app.db.session import get_db
from app.models import User
from app.schemas.auth import PasswordChange, Token, UserLogin, UserOut, UserRegister

router = APIRouter(prefix="/auth", tags=["auth"])
settings = get_settings()


def _require_allowed(email: str) -> None:
    """Refuse addresses outside the allowlist.

    This is a single-user tool; once deployed, open registration would let
    anyone who can reach the API create an account.
    """
    if not settings.email_allowed(email):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This deployment is restricted to its owner's account.",
        )


@router.post("/register", response_model=Token, status_code=status.HTTP_201_CREATED)
def register(payload: UserRegister, db: Session = Depends(get_db)) -> Token:
    _require_allowed(payload.email)
    existing = db.scalar(select(User).where(User.email == payload.email.lower()))
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Email already registered"
        )

    user = User(
        email=payload.email.lower(),
        hashed_password=hash_password(payload.password),
        full_name=payload.full_name,
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    return Token(access_token=create_access_token(str(user.id)), user=UserOut.model_validate(user))


@router.post("/login", response_model=Token)
def login(payload: UserLogin, db: Session = Depends(get_db)) -> Token:
    _require_allowed(payload.email)
    user = db.scalar(select(User).where(User.email == payload.email.lower()))
    # Same message for unknown email and wrong password — don't leak which
    # addresses are registered.
    if user is None or not verify_password(payload.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Incorrect email or password"
        )

    return Token(access_token=create_access_token(str(user.id)), user=UserOut.model_validate(user))


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(get_current_user)) -> User:
    return user


@router.post("/password", status_code=status.HTTP_204_NO_CONTENT)
def change_password(
    payload: PasswordChange,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> None:
    """Change the signed-in user's password.

    The current password is required, so a stolen session token alone cannot
    lock the owner out of their own account.
    """
    if not verify_password(payload.current_password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Current password is incorrect.",
        )
    if payload.new_password == payload.current_password:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="The new password must differ from the current one.",
        )

    user.hashed_password = hash_password(payload.new_password)
    db.commit()
