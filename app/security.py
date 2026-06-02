"""Password hashing, JWT access tokens, and the current-user dependency.

The hashing and token helpers are pure functions (no I/O), so they are unit-tested directly.
``get_current_user`` is the FastAPI dependency every protected route depends on: it turns a
bearer token into the authenticated ``User`` or rejects the request as unauthenticated.

Passwords are SHA-256 pre-hashed before bcrypt: bcrypt silently truncates input past 72
bytes, so without the pre-hash two long passwords sharing a 72-byte prefix would be treated
as equal. base64 of the digest (rather than the raw bytes, which can contain a NUL that
bcrypt's C string handling would truncate at) gives a fixed 44-char ASCII string.
"""

import base64
import datetime as dt
import hashlib
import logging

import bcrypt
import jwt
from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.errors import Unauthenticated
from app.logging_config import user_id_var
from app.models import User

logger = logging.getLogger(__name__)

_JWT_ALGORITHM = "HS256"

# auto_error=False: a missing or non-bearer Authorization header yields None here (not a
# framework 403), so get_current_user can raise the project's own 401 uniformly.
_bearer_scheme = HTTPBearer(auto_error=False)


def _prehash(password: str) -> str:
    """Return the bcrypt-safe SHA-256 pre-hash of a password (defeats bcrypt's 72-byte limit)."""
    digest = hashlib.sha256(password.encode("utf-8")).digest()
    return base64.b64encode(digest).decode("ascii")


def hash_password(password: str) -> str:
    """Return a salted bcrypt hash of the password, safe to persist."""
    return bcrypt.hashpw(_prehash(password).encode("ascii"), bcrypt.gensalt()).decode("ascii")


def verify_password(password: str, password_hash: str) -> bool:
    """Report whether the password matches the stored hash."""
    return bcrypt.checkpw(_prehash(password).encode("ascii"), password_hash.encode("ascii"))


def create_access_token(user_id: int) -> str:
    """Return a signed JWT identifying the user, expiring after the configured TTL.

    The ``sub`` claim carries the user id as a string (PyJWT round-trips ``sub`` as text);
    the TTL is read at call time so configuration changes take effect without a reimport.
    """
    expire = dt.datetime.now(tz=dt.timezone.utc) + dt.timedelta(
        minutes=settings.access_token_expire_minutes
    )
    return jwt.encode({"sub": str(user_id), "exp": expire}, settings.secret_key, algorithm=_JWT_ALGORITHM)


def decode_access_token(token: str) -> int:
    """Return the user id carried by a valid token, or raise ``Unauthenticated``.

    Rejects a token that is malformed, tampered with, signed with the wrong key, expired, or
    missing/with a non-integer subject — every failure maps to the same 401.
    """
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=[_JWT_ALGORITHM])
        return int(payload["sub"])
    except (jwt.InvalidTokenError, KeyError, ValueError) as exc:
        raise Unauthenticated("Invalid or expired token") from exc


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
    db: Session = Depends(get_db),
) -> User:
    """Resolve the authenticated user from the bearer token, or raise ``Unauthenticated``.

    A missing/malformed/expired token, or a token whose user no longer exists, is a 401. The
    resolved id is published to the logging context so every record for this request carries
    ``user_id``.
    """
    if credentials is None:
        raise Unauthenticated("Not authenticated")
    user_id = decode_access_token(credentials.credentials)
    user = db.get(User, user_id)
    if user is None:
        raise Unauthenticated("Not authenticated")
    user_id_var.set(user.id)
    return user
