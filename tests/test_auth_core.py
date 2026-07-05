from datetime import datetime, timedelta, timezone

import jwt
import pytest

from backend.core import auth


def test_password_hash_and_verify():
    hashed = auth.hash_password("correct horse battery staple")
    assert hashed != "correct horse battery staple"
    assert auth.verify_password("correct horse battery staple", hashed)
    assert not auth.verify_password("wrong password", hashed)


def test_access_token_round_trip():
    token = auth.create_access_token("user-123")
    assert auth.decode_access_token(token) == "user-123"


def test_access_token_rejects_wrong_type():
    now = datetime.now(timezone.utc)
    token = jwt.encode(
        {
            "sub": "user-123",
            "iat": int(now.timestamp()),
            "exp": int((now + timedelta(minutes=5)).timestamp()),
            "type": "refresh",
        },
        auth.AUTH_SECRET_KEY,
        algorithm=auth.ALGORITHM,
    )
    with pytest.raises(jwt.InvalidTokenError):
        auth.decode_access_token(token)


def test_access_token_rejects_expired_token():
    now = datetime.now(timezone.utc)
    token = jwt.encode(
        {
            "sub": "user-123",
            "iat": int((now - timedelta(minutes=10)).timestamp()),
            "exp": int((now - timedelta(minutes=5)).timestamp()),
            "type": "access",
        },
        auth.AUTH_SECRET_KEY,
        algorithm=auth.ALGORITHM,
    )
    with pytest.raises(jwt.ExpiredSignatureError):
        auth.decode_access_token(token)


def test_refresh_token_hash_is_stable_and_not_plaintext():
    opaque, token_hash = auth.new_refresh_token()
    assert token_hash == auth.refresh_token_hash(opaque)
    assert token_hash != opaque
    assert len(token_hash) == 64
