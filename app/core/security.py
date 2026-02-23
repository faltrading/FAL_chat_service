import uuid

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.config import settings
from app.schemas.auth import CurrentUser

security_scheme = HTTPBearer()


def decode_jwt_token(token: str) -> dict:
    try:
        payload = jwt.decode(
            token,
            settings.JWT_SECRET_KEY,
            algorithms=[settings.JWT_ALGORITHM],
        )
        return payload
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token scaduto",
        )
    except jwt.InvalidTokenError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token non valido",
        )


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security_scheme),
) -> CurrentUser:
    payload = decode_jwt_token(credentials.credentials)
    try:
        username = payload["username"]
        role = payload.get("role", "user")
        # Se il token non ha role ma l'utente è l'admin configurato, assegna admin
        if role != "admin" and username == settings.ADMIN_USERNAME:
            role = "admin"
        return CurrentUser(
            user_id=uuid.UUID(payload["sub"]),
            username=username,
            role=role,
        )
    except (KeyError, ValueError):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Payload del token non valido",
        )


async def require_admin(
    current_user: CurrentUser = Depends(get_current_user),
) -> CurrentUser:
    if not current_user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Accesso riservato agli amministratori",
        )
    return current_user


def decode_ws_token(token: str) -> CurrentUser | None:
    try:
        payload = jwt.decode(
            token,
            settings.JWT_SECRET_KEY,
            algorithms=[settings.JWT_ALGORITHM],
        )
        return CurrentUser(
            user_id=uuid.UUID(payload["sub"]),
            username=payload["username"],
            role=payload.get("role", "user"),
        )
    except Exception:
        return None
