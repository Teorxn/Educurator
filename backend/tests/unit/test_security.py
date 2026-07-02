"""
#26 — Unit tests for security utilities (JWT, password hashing).

Covers:
  - hash_password and verify_password with bcrypt
  - create_access_token and decode_token
  - create_refresh_token
  - Token type fields
  - Expiration handling
"""

from datetime import datetime, timedelta, timezone

import pytest
from app.config import settings
from app.utils.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    verify_password,
)


class TestPasswordHashing:
    """Password hashing with bcrypt."""

    def test_hash_and_verify(self):
        """Hashed password can be verified with the original plain text."""
        password = "SecureP@ss123!"
        hashed = hash_password(password)

        assert hashed != password
        assert verify_password(password, hashed) is True

    def test_wrong_password_fails(self):
        """Wrong password does not pass verification."""
        password = "SecureP@ss123!"
        hashed = hash_password(password)

        assert verify_password("WrongPassword", hashed) is False

    def test_hash_is_different_each_time(self):
        """Each hash call produces a different bcrypt salt."""
        password = "SamePassword"
        hash_a = hash_password(password)
        hash_b = hash_password(password)

        assert hash_a != hash_b
        # Both should verify correctly though
        assert verify_password(password, hash_a) is True
        assert verify_password(password, hash_b) is True

    def test_empty_password(self):
        """Empty password can be hashed and verified."""
        hashed = hash_password("")
        assert verify_password("", hashed) is True
        assert verify_password("x", hashed) is False


class TestAccessToken:
    """JWT access token creation and decoding."""

    def test_create_and_decode(self):
        """Access token can be created and decoded."""
        data = {"sub": "user-123", "role": "instructor"}
        token = create_access_token(data)
        payload = decode_token(token)

        assert payload["sub"] == "user-123"
        assert payload["role"] == "instructor"
        assert payload["type"] == "access"
        assert "exp" in payload

    def test_expiration_time(self):
        """Access token has the configured expiration."""
        data = {"sub": "user-456"}
        token = create_access_token(data)
        payload = decode_token(token)

        exp = datetime.fromtimestamp(payload["exp"], tz=timezone.utc)
        now = datetime.now(timezone.utc)
        expected_delta = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)

        # Allow 5 seconds tolerance
        assert abs((exp - now) - expected_delta) < timedelta(seconds=5)

    def test_preserves_additional_fields(self):
        """Additional data fields are preserved in the token."""
        data = {"sub": "user-789", "custom_field": "custom_value"}
        token = create_access_token(data)
        payload = decode_token(token)

        assert payload["custom_field"] == "custom_value"


class TestRefreshToken:
    """JWT refresh token creation and decoding."""

    def test_create_and_decode(self):
        """Refresh token can be created and decoded."""
        data = {"sub": "user-123"}
        token = create_refresh_token(data)
        payload = decode_token(token)

        assert payload["sub"] == "user-123"
        assert payload["type"] == "refresh"

    def test_expiration_time(self):
        """Refresh token has the configured expiration (days)."""
        data = {"sub": "user-456"}
        token = create_refresh_token(data)
        payload = decode_token(token)

        exp = datetime.fromtimestamp(payload["exp"], tz=timezone.utc)
        now = datetime.now(timezone.utc)
        expected_delta = timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)

        # Allow 5 seconds tolerance
        assert abs((exp - now) - expected_delta) < timedelta(seconds=5)


class TestDecodeToken:
    """Token decoding edge cases."""

    def test_invalid_token_raises_error(self):
        """Invalid token raises an exception during decode."""
        with pytest.raises(Exception):
            decode_token("invalid-token-string")

    def test_tampered_token_raises_error(self):
        """Tampered token signature raises an exception."""
        data = {"sub": "user-123"}
        token = create_access_token(data)
        # Tamper with the payload part
        parts = token.split(".")
        tampered = f"{parts[0]}.tampered.{parts[2]}"

        with pytest.raises(Exception):
            decode_token(tampered)

    def test_expired_token(self):
        """Expired token raises an exception."""
        from app.config import settings
        from jose import jwt

        # Create a token that expired 1 hour ago
        payload = {
            "sub": "user-expired",
            "exp": datetime.now(timezone.utc) - timedelta(hours=1),
            "type": "access",
        }
        token = jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.ALGORITHM)

        with pytest.raises(Exception):
            decode_token(token)
