"""Claim legacy workspaces for one user.

Pre-auth databases may contain workspaces with owner_user_id NULL. The shared
demo workspace (arxiv_seed) must stay public, but all other legacy workspaces can
be assigned to a real user with:

    python scripts/claim_workspaces.py --email user@example.com
"""
import argparse

from sqlalchemy import select

from backend.db.models import User, Workspace
from backend.db.postgres import SessionLocal


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--email", required=True, help="Account email to claim legacy workspaces")
    args = parser.parse_args()
    email = args.email.strip().lower()

    db = SessionLocal()
    try:
        user = db.execute(select(User).where(User.email == email)).scalar_one_or_none()
        if user is None:
            print(f"No user found for {email}")
            return 1

        workspaces = (
            db.execute(
                select(Workspace).where(
                    Workspace.owner_user_id.is_(None),
                    Workspace.id != "arxiv_seed",
                )
            )
            .scalars()
            .all()
        )
        for workspace in workspaces:
            workspace.owner_user_id = user.id
        db.commit()

        print(f"Claimed {len(workspaces)} workspace(s) for {email}")
        for workspace in workspaces:
            print(f"- {workspace.id}: {workspace.name}")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
