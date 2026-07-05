from fastapi import Depends, HTTPException, Request
from jwt import InvalidTokenError
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.auth import ACCESS_COOKIE, decode_access_token
from backend.db.models import Conversation, Report, User, Workspace
from backend.db.postgres import get_async_db


async def get_current_user(
    request: Request,
    db: AsyncSession = Depends(get_async_db),
) -> User:
    token = None
    auth_header = request.headers.get("authorization", "")
    if auth_header.lower().startswith("bearer "):
        token = auth_header.split(" ", 1)[1].strip()
    if not token:
        token = request.cookies.get(ACCESS_COOKIE)
    if not token:
        raise HTTPException(status_code=401, detail="Authentication required")

    try:
        user_id = decode_access_token(token)
    except InvalidTokenError:
        raise HTTPException(status_code=401, detail="Authentication required")

    user = (
        await db.execute(select(User).where(User.id == user_id, User.is_active.is_(True)))
    ).scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=401, detail="Authentication required")
    request.state.user_id = user.id
    return user


async def require_readable_workspace(
    db: AsyncSession,
    workspace_id: str,
    user: User,
) -> Workspace:
    workspace = (
        await db.execute(
            select(Workspace).where(
                Workspace.id == workspace_id,
                or_(Workspace.owner_user_id == user.id, Workspace.owner_user_id.is_(None)),
            )
        )
    ).scalar_one_or_none()
    if workspace is None:
        raise HTTPException(status_code=404, detail="Workspace not found")
    return workspace


async def require_owned_workspace(
    db: AsyncSession,
    workspace_id: str,
    user: User,
) -> Workspace:
    workspace = (
        await db.execute(
            select(Workspace).where(
                Workspace.id == workspace_id,
                Workspace.owner_user_id == user.id,
            )
        )
    ).scalar_one_or_none()
    if workspace is None:
        raise HTTPException(status_code=404, detail="Workspace not found")
    return workspace


async def get_readable_workspace(
    workspace_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db),
) -> Workspace:
    return await require_readable_workspace(db, workspace_id, user)


async def get_owned_workspace(
    workspace_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db),
) -> Workspace:
    return await require_owned_workspace(db, workspace_id, user)


def row_visible_in_workspace(row: Report | Conversation, workspace: Workspace, user: User) -> bool:
    if workspace.owner_user_id is not None:
        return True
    return row.user_id == user.id or row.user_id is None


def row_delete_allowed(row: Report | Conversation, workspace: Workspace, user: User) -> bool:
    return workspace.owner_user_id == user.id or row.user_id == user.id
