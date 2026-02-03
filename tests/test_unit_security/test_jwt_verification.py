"""
Tests for JWT verification functions.
"""

from unittest.mock import patch

import pytest
from jose import JWTError

from app.core.security.jwt_verification import (
    get_rsa_key,
    get_rsa_key_async,
    verify_token,
    verify_token_async,
)


class TestRSAKeyLookup:
    @pytest.mark.anyio
    async def test_get_rsa_key_success(self):
        with patch("app.core.security.jwt_verification.get_jwks") as mock_get_jwks:
            mock_get_jwks.return_value = {
                "keys": [
                    {
                        "kid": "test-kid",
                        "kty": "RSA",
                        "use": "sig",
                        "n": "test-n",
                        "e": "test-e",
                    }
                ]
            }

            with patch(
                "app.core.security.jwt_verification.jwt.get_unverified_header"
            ) as mock_header:
                mock_header.return_value = {"kid": "test-kid"}

                key = get_rsa_key("fake.token")
                assert key["kid"] == "test-kid"

    @pytest.mark.anyio
    async def test_get_rsa_key_not_found(self):
        with patch("app.core.security.jwks_cache.get_jwks") as mock_get_jwks:
            mock_get_jwks.return_value = {"keys": [{"kid": "other-kid"}]}

            with patch(
                "app.core.security.jwt_verification.jwt.get_unverified_header"
            ) as mock_header:
                mock_header.return_value = {"kid": "test-kid"}

                with pytest.raises(Exception):
                    get_rsa_key("fake.token")

    @pytest.mark.anyio
    async def test_get_rsa_key_jwt_error(self):
        with patch("app.core.security.jwks_cache.get_jwks") as mock_get_jwks:
            mock_get_jwks.return_value = {"keys": [{"kid": "test", "kty": "RSA"}]}

            with patch(
                "app.core.security.jwt_verification.jwt.get_unverified_header"
            ) as mock_header:
                mock_header.side_effect = JWTError("Invalid header")

                with pytest.raises(Exception):
                    get_rsa_key("bad.token")

    @pytest.mark.anyio
    async def test_get_rsa_key_missing_kid_in_header(self):
        with patch("app.core.security.jwks_cache.get_jwks") as mock_get_jwks:
            mock_get_jwks.return_value = {"keys": [{"kid": "test", "kty": "RSA"}]}

            with patch(
                "app.core.security.jwt_verification.jwt.get_unverified_header"
            ) as mock_header:
                mock_header.return_value = {}

                with pytest.raises(Exception):
                    get_rsa_key("token.without.kid")

    @pytest.mark.anyio
    async def test_get_rsa_key_no_matching_key(self):
        with patch("app.core.security.jwks_cache.get_jwks") as mock_get_jwks:
            mock_get_jwks.return_value = {"keys": [{"kid": "other", "kty": "RSA"}]}

            with patch(
                "app.core.security.jwt_verification.jwt.get_unverified_header"
            ) as mock_header:
                mock_header.return_value = {"kid": "notfound"}

                with pytest.raises(Exception):
                    get_rsa_key("token.with.unknown.kid")


class TestTokenVerification:
    @pytest.mark.anyio
    async def test_verify_token_success(self):
        with patch("app.core.security.jwks_cache.get_jwks") as mock_get_jwks:
            mock_get_jwks.return_value = {"keys": [{"kid": "test"}]}

            with patch("app.core.security.jwt_verification.jwt.decode") as mock_decode:
                mock_decode.return_value = {"sub": "user123"}

                with patch("app.core.security.jwt_verification.get_rsa_key") as mock_get_key:
                    mock_get_key.return_value = {"kty": "RSA"}

                    result = verify_token("fake.token.here")
                    assert result == {"sub": "user123"}

    @pytest.mark.anyio
    async def test_verify_token_with_expired_token(self):
        from jose import jwt as jose_jwt

        with patch("app.core.security.jwks_cache.get_jwks") as mock_get_jwks:
            mock_get_jwks.return_value = {"keys": [{"kid": "test", "kty": "RSA"}]}

            with patch("app.core.security.jwt_verification.jwt.decode") as mock_decode:
                mock_decode.side_effect = jose_jwt.ExpiredSignatureError("Token expired")

                with patch("app.core.security.jwt_verification.get_rsa_key") as mock_get_key:
                    mock_get_key.return_value = {"kty": "RSA"}

                    with pytest.raises(Exception):
                        verify_token("expired.token")

    @pytest.mark.anyio
    async def test_verify_token_with_invalid_signature(self):
        with patch("app.core.security.jwks_cache.get_jwks") as mock_get_jwks:
            mock_get_jwks.return_value = {"keys": [{"kid": "test", "kty": "RSA"}]}

            with patch("app.core.security.jwt_verification.jwt.decode") as mock_decode:
                mock_decode.side_effect = JWTError("Invalid signature")

                with patch("app.core.security.jwt_verification.get_rsa_key") as mock_get_key:
                    mock_get_key.return_value = {"kty": "RSA"}

                    with pytest.raises(Exception):
                        verify_token("invalid.token")

    @pytest.mark.anyio
    async def test_verify_token_generic_jwt_error(self):
        with patch("app.core.security.jwks_cache.get_jwks") as mock_get_jwks:
            mock_get_jwks.return_value = {"keys": [{"kid": "test", "kty": "RSA"}]}

            with patch("app.core.security.jwt_verification.jwt.decode") as mock_decode:
                mock_decode.side_effect = JWTError("JWT error")

                with patch("app.core.security.jwt_verification.get_rsa_key") as mock_get_key:
                    mock_get_key.return_value = {"kty": "RSA"}

                    with pytest.raises(Exception):
                        verify_token("bad.token")

    @pytest.mark.anyio
    async def test_verify_token_unexpected_error(self):
        with patch("app.core.security.jwks_cache.get_jwks") as mock_get_jwks:
            mock_get_jwks.return_value = {"keys": [{"kid": "test", "kty": "RSA"}]}

            with patch("app.core.security.jwt_verification.jwt.decode") as mock_decode:
                mock_decode.side_effect = RuntimeError("Unexpected error")

                with patch("app.core.security.jwt_verification.get_rsa_key") as mock_get_key:
                    mock_get_key.return_value = {"kty": "RSA"}

                    with pytest.raises(Exception):
                        verify_token("bad.token")

    @pytest.mark.anyio
    async def test_verify_token_success_with_logging(self):
        with patch("app.core.security.jwks_cache.get_jwks") as mock_get_jwks:
            mock_get_jwks.return_value = {"keys": [{"kid": "test", "kty": "RSA"}]}

            with patch("app.core.security.jwt_verification.jwt.decode") as mock_decode:
                mock_decode.return_value = {"sub": "user123", "aud": "test"}

                with patch("app.core.security.jwt_verification.get_rsa_key") as mock_get_key:
                    mock_get_key.return_value = {"kty": "RSA"}

                    with patch("app.core.security.jwt_verification.logger") as mock_logger:
                        result = verify_token("valid.token")

                        assert result == {"sub": "user123", "aud": "test"}
                        mock_logger.debug.assert_called()


class TestAsyncTokenVerification:
    @pytest.mark.anyio
    async def test_get_rsa_key_async_success(self):
        with patch("app.core.security.jwt_verification.get_jwks_async") as mock_get_jwks:
            mock_get_jwks.return_value = {
                "keys": [
                    {
                        "kid": "test-kid",
                        "kty": "RSA",
                        "use": "sig",
                        "n": "test-n",
                        "e": "test-e",
                    }
                ]
            }

            with patch(
                "app.core.security.jwt_verification.jwt.get_unverified_header"
            ) as mock_header:
                mock_header.return_value = {"kid": "test-kid"}

                key = await get_rsa_key_async("fake.token")
                assert key["kid"] == "test-kid"
                assert key["kty"] == "RSA"

    @pytest.mark.anyio
    async def test_get_rsa_key_async_not_found(self):
        from app.core.errors import UnauthorizedError

        with patch("app.core.security.jwks_cache.get_jwks_async") as mock_get_jwks:
            mock_get_jwks.return_value = {"keys": [{"kid": "other-kid"}]}

            with patch(
                "app.core.security.jwt_verification.jwt.get_unverified_header"
            ) as mock_header:
                mock_header.return_value = {"kid": "test-kid"}

                with pytest.raises(UnauthorizedError):
                    await get_rsa_key_async("fake.token")

    @pytest.mark.anyio
    async def test_get_rsa_key_async_jwt_error(self):
        from app.core.errors import UnauthorizedError

        with patch("app.core.security.jwks_cache.get_jwks_async") as mock_get_jwks:
            mock_get_jwks.return_value = {"keys": [{"kid": "test"}]}

            with patch(
                "app.core.security.jwt_verification.jwt.get_unverified_header"
            ) as mock_header:
                mock_header.side_effect = JWTError("Invalid header")

                with pytest.raises(UnauthorizedError):
                    await get_rsa_key_async("bad.token")

    @pytest.mark.anyio
    async def test_verify_token_async_success(self):
        with patch("app.core.security.jwt_verification.get_rsa_key_async") as mock_get_key:
            mock_get_key.return_value = {"kty": "RSA"}

            with patch("app.core.security.jwt_verification.jwt.decode") as mock_decode:
                mock_decode.return_value = {"sub": "user123", "aud": "test"}

                result = await verify_token_async("valid.token")
                assert result == {"sub": "user123", "aud": "test"}

    @pytest.mark.anyio
    async def test_verify_token_async_expired(self):
        from jose import jwt as jose_jwt

        from app.core.errors import UnauthorizedError

        with patch("app.core.security.jwt_verification.get_rsa_key_async") as mock_get_key:
            mock_get_key.return_value = {"kty": "RSA"}

            with patch("app.core.security.jwt_verification.jwt.decode") as mock_decode:
                mock_decode.side_effect = jose_jwt.ExpiredSignatureError("Expired")

                with pytest.raises(UnauthorizedError) as exc_info:
                    await verify_token_async("expired.token")

                assert "Invalid or expired token" in str(exc_info.value)

    @pytest.mark.anyio
    async def test_verify_token_async_claims_error(self):
        from jose import jwt as jose_jwt

        from app.core.errors import UnauthorizedError

        with patch("app.core.security.jwt_verification.get_rsa_key_async") as mock_get_key:
            mock_get_key.return_value = {"kty": "RSA"}

            with patch("app.core.security.jwt_verification.jwt.decode") as mock_decode:
                mock_decode.side_effect = jose_jwt.JWTClaimsError("Invalid claims")

                with pytest.raises(UnauthorizedError):
                    await verify_token_async("invalid.token")

    @pytest.mark.anyio
    async def test_verify_token_async_jwt_error(self):
        from app.core.errors import UnauthorizedError

        with patch("app.core.security.jwt_verification.get_rsa_key_async") as mock_get_key:
            mock_get_key.return_value = {"kty": "RSA"}

            with patch("app.core.security.jwt_verification.jwt.decode") as mock_decode:
                mock_decode.side_effect = JWTError("JWT error")

                with pytest.raises(UnauthorizedError):
                    await verify_token_async("bad.token")

    @pytest.mark.anyio
    async def test_verify_token_async_unexpected_error(self):
        from app.core.errors import UnauthorizedError

        with patch("app.core.security.jwt_verification.get_rsa_key_async") as mock_get_key:
            mock_get_key.return_value = {"kty": "RSA"}

            with patch("app.core.security.jwt_verification.jwt.decode") as mock_decode:
                mock_decode.side_effect = RuntimeError("Unexpected")

                with pytest.raises(UnauthorizedError):
                    await verify_token_async("bad.token")


class TestJWKSGlobalFunctions:
    @pytest.mark.anyio
    async def test_global_get_jwks_function(self):
        from app.core.security.jwks_cache import _jwks_cache, get_jwks

        with patch.object(_jwks_cache, "get_jwks") as mock_get:
            mock_get.return_value = {"keys": [{"kid": "test"}]}

            result = get_jwks()
            assert result == {"keys": [{"kid": "test"}]}

    @pytest.mark.anyio
    async def test_global_get_jwks_async_function(self):
        from app.core.security.jwks_cache import _jwks_cache, get_jwks_async

        with patch.object(_jwks_cache, "get_jwks_async") as mock_get:
            mock_get.return_value = {"keys": [{"kid": "test"}]}

            result = await get_jwks_async()
            assert result == {"keys": [{"kid": "test"}]}

    @pytest.mark.anyio
    async def test_clear_jwks_cache(self):
        from datetime import UTC, datetime

        from app.core.security.jwks_cache import _jwks_cache, clear_jwks_cache

        _jwks_cache._cache = {"keys": [{"kid": "test"}]}
        _jwks_cache._cache_time = datetime.now(UTC)

        clear_jwks_cache()

        assert _jwks_cache._cache is None
        assert _jwks_cache._cache_time is None
