import base64
import hashlib
from datetime import UTC, datetime, timedelta
from typing import Any

import bcrypt
from jose import JWTError, jwt

from app.core.config import get_settings

settings = get_settings()


def _prehash(plain: str) -> bytes:
    """Reduce a password to a fixed 44-byte digest before bcrypt.

    bcrypt silently truncates anything past 72 bytes, which would make two long
    passwords sharing a 72-byte prefix interchangeable. SHA-256 + base64 keeps
    the full password significant at a constant, always-under-72 length.
    """
    return base64.b64encode(hashlib.sha256(plain.encode("utf-8")).digest())


def hash_password(plain: str) -> str:
    return bcrypt.hashpw(_prehash(plain), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(_prehash(plain), hashed.encode("utf-8"))
    except ValueError:
        # Malformed hash in the database — treat as a failed login, not a crash.
        return False


def create_access_token(subject: str, expires_delta: timedelta | None = None) -> str:
    expire = datetime.now(UTC) + (
        expires_delta or timedelta(minutes=settings.access_token_expire_minutes)
    )
    payload = {"sub": subject, "exp": expire, "iat": datetime.now(UTC)}
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str) -> dict[str, Any] | None:
    try:
        return jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
    except JWTError:
        return None
