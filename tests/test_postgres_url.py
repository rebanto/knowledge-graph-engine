import os

os.environ.setdefault(
    "POSTGRES_URL",
    "postgresql://test_user:test_password@localhost/test_db?sslmode=disable",
)

from backend.db.postgres import _build_async_url


def test_async_postgres_url_preserves_real_password():
    async_url, connect_args = _build_async_url(
        "postgresql://neondb_owner:p%40ss%3Aword@ep-test-pooler.us-east-2.aws.neon.tech/"
        "neondb?sslmode=require&channel_binding=require"
    )

    assert async_url == (
        "postgresql+asyncpg://neondb_owner:p%40ss%3Aword@"
        "ep-test-pooler.us-east-2.aws.neon.tech/neondb"
    )
    assert "***" not in async_url
    assert connect_args == {"ssl": True}
