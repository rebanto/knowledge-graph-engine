import os
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from backend.api.deps import get_current_user
from backend.core import auth as auth_core
from backend.core.ratelimit import AUTH_LIMIT, limiter
from backend.db.models import RefreshToken, User
from backend.db.postgres import get_async_db
from backend.models.schemas import AuthRequest, UserResponse

router = APIRouter(prefix="/auth", tags=["auth"])


def _registration_enabled() -> bool:
    return os.environ.get("REGISTRATION_ENABLED", "true").lower() == "true"


def _normalize_email(email: str) -> str:
    return email.strip().lower()


async def _issue_session(response: Response, db: AsyncSession, user: User) -> None:
    access_token = auth_core.create_access_token(user.id)
    opaque, token_hash = auth_core.new_refresh_token()
    refresh = RefreshToken(
        id=str(uuid.uuid4()),
        user_id=user.id,
        token_hash=token_hash,
        expires_at=datetime.now(timezone.utc) + auth_core.refresh_ttl(),
    )
    db.add(refresh)
    await db.flush()
    auth_core.set_auth_cookies(response, access_token, opaque)


@router.post("/register", response_model=UserResponse)
@limiter.limit(AUTH_LIMIT)
async def register(
    request: Request,
    response: Response,
    body: AuthRequest,
    db: AsyncSession = Depends(get_async_db),
):
    if not _registration_enabled():
        raise HTTPException(status_code=403, detail="Registration is disabled")
    email = _normalize_email(str(body.email))
    exists = (await db.execute(select(User).where(User.email == email))).scalar_one_or_none()
    if exists is not None:
        raise HTTPException(status_code=409, detail="An account with that email already exists")
    user = User(
        id=str(uuid.uuid4()),
        email=email,
        password_hash=auth_core.hash_password(body.password),
        created_at=datetime.now(timezone.utc),
        is_active=True,
    )
    db.add(user)
    await _issue_session(response, db, user)
    await db.commit()
    await db.refresh(user)
    return user


@router.post("/login", response_model=UserResponse)
@limiter.limit(AUTH_LIMIT)
async def login(
    request: Request,
    response: Response,
    body: AuthRequest,
    db: AsyncSession = Depends(get_async_db),
):
    email = _normalize_email(str(body.email))
    user = (await db.execute(select(User).where(User.email == email))).scalar_one_or_none()
    if user is None or not user.is_active or not auth_core.verify_password(body.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid email or password")
    await _issue_session(response, db, user)
    await db.commit()
    return user


@router.post("/refresh", response_model=UserResponse)
@limiter.limit(AUTH_LIMIT)
async def refresh(
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_async_db),
):
    opaque = request.cookies.get(auth_core.REFRESH_COOKIE)
    if not opaque:
        raise HTTPException(status_code=401, detail="Authentication required")
    token_hash = auth_core.refresh_token_hash(opaque)
    refresh_token = (
        await db.execute(select(RefreshToken).where(RefreshToken.token_hash == token_hash))
    ).scalar_one_or_none()
    if refresh_token is None:
        raise HTTPException(status_code=401, detail="Authentication required")

    now = datetime.now(timezone.utc)
    user = (
        await db.execute(
            select(User).where(User.id == refresh_token.user_id, User.is_active.is_(True))
        )
    ).scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=401, detail="Authentication required")

    if refresh_token.revoked_at is not None:
        await db.execute(
            update(RefreshToken)
            .where(RefreshToken.user_id == refresh_token.user_id, RefreshToken.revoked_at.is_(None))
            .values(revoked_at=now)
        )
        await db.commit()
        auth_core.clear_auth_cookies(response)
        raise HTTPException(status_code=401, detail="Authentication required")

    expires_at = refresh_token.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if expires_at <= now:
        refresh_token.revoked_at = now
        await db.commit()
        auth_core.clear_auth_cookies(response)
        raise HTTPException(status_code=401, detail="Authentication required")

    new_opaque, new_hash = auth_core.new_refresh_token()
    new_refresh = RefreshToken(
        id=str(uuid.uuid4()),
        user_id=user.id,
        token_hash=new_hash,
        expires_at=now + auth_core.refresh_ttl(),
    )
    db.add(new_refresh)
    refresh_token.revoked_at = now
    refresh_token.replaced_by = new_refresh.id
    access_token = auth_core.create_access_token(user.id)
    auth_core.set_auth_cookies(response, access_token, new_opaque)
    await db.commit()
    return user


@router.post("/logout", status_code=204)
async def logout(
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_async_db),
):
    opaque = request.cookies.get(auth_core.REFRESH_COOKIE)
    if opaque:
        token_hash = auth_core.refresh_token_hash(opaque)
        refresh_token = (
            await db.execute(select(RefreshToken).where(RefreshToken.token_hash == token_hash))
        ).scalar_one_or_none()
        if refresh_token and refresh_token.revoked_at is None:
            refresh_token.revoked_at = datetime.now(timezone.utc)
            await db.commit()
    auth_core.clear_auth_cookies(response)


@router.get("/me", response_model=UserResponse)
async def me(user: User = Depends(get_current_user)):
    return user
