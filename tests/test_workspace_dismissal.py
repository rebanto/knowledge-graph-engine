from datetime import datetime, timezone

import pytest
from fastapi import HTTPException
from sqlalchemy.dialects import postgresql

from backend.api.deps import require_owned_workspace
from backend.api.routes.workspaces import dismiss_workspace, list_workspaces
from backend.db.models import User, Workspace
from backend.models.schemas import WorkspaceResponse


class _ScalarList:
    def __init__(self, values):
        self._values = values

    def all(self):
        return list(self._values)


class _Result:
    def __init__(self, values):
        self._values = values

    def scalars(self):
        return _ScalarList(self._values)

    def scalar_one_or_none(self):
        return self._values[0] if self._values else None


class _DismissalDb:
    def __init__(self, workspaces, user_id):
        self.workspaces = list(workspaces)
        self.user_id = user_id
        self.dismissals: set[tuple[str, str]] = set()
        self.commits = 0
        self.saw_dismissal_filter = False

    async def execute(self, stmt):
        sql = str(stmt.compile(dialect=postgresql.dialect()))
        if "INSERT INTO workspace_dismissals" in sql:
            params = stmt.compile(dialect=postgresql.dialect()).params
            self.dismissals.add((params["user_id"], params["workspace_id"]))
            return _Result([])

        assert "FROM workspaces" in sql
        self.saw_dismissal_filter = (
            "workspace_dismissals" in sql and "NOT IN" in sql.upper()
        )
        visible = [
            w
            for w in self.workspaces
            if (w.owner_user_id == self.user_id or w.owner_user_id is None)
            and (self.user_id, w.id) not in self.dismissals
        ]
        visible.sort(key=lambda w: w.created_at)
        return _Result(visible)

    async def commit(self):
        self.commits += 1


class _OwnedWorkspaceDb:
    def __init__(self, workspace):
        self.workspace = workspace
        self.calls = 0

    async def execute(self, stmt):
        self.calls += 1
        if self.calls == 1:
            return _Result([])
        return _Result([self.workspace])


def _workspace(id, owner_user_id, created_at):
    return Workspace(
        id=id,
        name=id,
        domain="AI",
        owner_user_id=owner_user_id,
        created_at=created_at,
    )


async def test_dismiss_hides_demo_from_list_and_is_idempotent():
    user = User(id="user-1", email="u@example.com", password_hash="hash")
    demo = _workspace("demo", None, datetime(2026, 1, 1, tzinfo=timezone.utc))
    owned = _workspace("owned", user.id, datetime(2026, 1, 2, tzinfo=timezone.utc))
    other = _workspace("other", "user-2", datetime(2026, 1, 3, tzinfo=timezone.utc))
    db = _DismissalDb([demo, owned, other], user.id)

    before = await list_workspaces(user=user, db=db)
    assert [w.id for w in before] == ["demo", "owned"]
    assert db.saw_dismissal_filter

    await dismiss_workspace("demo", workspace=demo, user=user, db=db)
    await dismiss_workspace("demo", workspace=demo, user=user, db=db)

    assert db.dismissals == {(user.id, "demo")}
    assert db.commits == 2
    after = await list_workspaces(user=user, db=db)
    assert [w.id for w in after] == ["owned"]


async def test_dismissing_owned_workspace_returns_400():
    user = User(id="user-1", email="u@example.com", password_hash="hash")
    owned = _workspace("owned", user.id, datetime.now(timezone.utc))
    db = _DismissalDb([owned], user.id)

    with pytest.raises(HTTPException) as exc:
        await dismiss_workspace("owned", workspace=owned, user=user, db=db)

    assert exc.value.status_code == 400


async def test_demo_source_mutation_guard_still_403s():
    user = User(id="user-1", email="u@example.com", password_hash="hash")
    demo = _workspace("demo", None, datetime.now(timezone.utc))
    db = _OwnedWorkspaceDb(demo)

    with pytest.raises(HTTPException) as exc:
        await require_owned_workspace(db, "demo", user)

    assert exc.value.status_code == 403
    assert "read-only demo" in exc.value.detail


def test_workspace_response_exposes_read_only_from_owner():
    demo = _workspace("demo", None, datetime.now(timezone.utc))
    owned = _workspace("owned", "user-1", datetime.now(timezone.utc))

    validate = getattr(WorkspaceResponse, "model_validate", WorkspaceResponse.from_orm)
    assert validate(demo).read_only is True
    assert validate(owned).read_only is False
