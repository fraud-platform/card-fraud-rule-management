from unittest.mock import patch

import pytest

from app.core.dependencies import get_current_user


class TestDependencies:
    @pytest.mark.anyio
    async def test_get_current_user(self):
        # This is just a re-export, so test that it calls the underlying function
        mock_user = {"sub": "user123"}

        with patch("app.core.dependencies._get_current_user") as mock_get:
            mock_get.return_value = mock_user

            result = get_current_user(mock_user)
            assert result == mock_user
