"""Tests for database connection and session management.

Tests synchronous SQLAlchemy functionality.
"""

from unittest.mock import MagicMock, patch

import pytest

from app.core.db import get_engine


class TestDatabaseSync:
    """Test synchronous database functionality."""

    @pytest.mark.anyio
    async def test_get_engine_creates_engine(self):
        with patch("app.core.db.settings") as mock_settings:
            mock_settings.database_url_app = "postgresql://user:pass@localhost/testdb"
            mock_settings.sync_url = "postgresql+psycopg://user:pass@localhost/testdb"

            # Reset global state
            import app.core.db

            app.core.db._engine = None

            engine = get_engine()
            assert engine is not None

            # Check that URL was modified for psycopg
            # The engine should have the modified URL
            assert "+psycopg" in str(engine.url)

    @pytest.mark.anyio
    async def test_get_engine_reuses_existing(self):
        with patch("app.core.db.settings") as mock_settings:
            mock_settings.database_url_app = "postgresql://user:pass@localhost/testdb"
            mock_settings.sync_url = "postgresql+psycopg://user:pass@localhost/testdb"

            # Reset global state
            import app.core.db

            app.core.db._engine = None

            engine1 = get_engine()
            engine2 = get_engine()
            assert engine1 is engine2

    @pytest.mark.anyio
    async def test_get_sessionmaker_creates_sessionmaker(self):
        with patch("app.core.db.settings") as mock_settings:
            mock_settings.database_url_app = "postgresql://user:pass@localhost/testdb"
            mock_settings.sync_url = "postgresql+psycopg://user:pass@localhost/testdb"

            # Reset global state
            import app.core.db

            app.core.db._engine = None
            app.core.db._sessionmaker = None

            from app.core.db import get_sessionmaker

            sessionmaker_obj = get_sessionmaker()
            assert sessionmaker_obj is not None

    @pytest.mark.anyio
    async def test_get_sessionmaker_reuses_existing(self):
        with patch("app.core.db.settings") as mock_settings:
            mock_settings.database_url_app = "postgresql://user:pass@localhost/testdb"
            mock_settings.sync_url = "postgresql+psycopg://user:pass@localhost/testdb"

            # Reset global state
            import app.core.db

            app.core.db._engine = None
            app.core.db._sessionmaker = None

            from app.core.db import get_sessionmaker

            sm1 = get_sessionmaker()
            sm2 = get_sessionmaker()
            assert sm1 is sm2


class TestDbSession:
    """Test database session context manager."""

    @pytest.mark.anyio
    async def test_get_db_session_yields_session(self):
        """Test that db session yields a Session."""
        with patch("app.core.db.settings") as mock_settings:
            mock_settings.database_url_app = "postgresql://user:pass@localhost/testdb"

            # Reset global state
            import app.core.db

            app.core.db._engine = None
            app.core.db._sessionmaker = None

            from app.core.db import get_db_session

            # Mock the session
            mock_session = MagicMock()

            with patch("app.core.db.get_sessionmaker") as mock_get_sm:
                mock_sm = MagicMock()
                mock_sm.return_value = mock_session
                mock_get_sm.return_value = mock_sm

                sessions = list(get_db_session())
                assert len(sessions) == 1
                assert sessions[0] is mock_session

    @pytest.mark.anyio
    async def test_get_db_session_closes_on_exit(self):
        """Test that db session closes after use."""
        with patch("app.core.db.settings") as mock_settings:
            mock_settings.database_url_app = "postgresql://user:pass@localhost/testdb"

            # Reset global state
            import app.core.db

            app.core.db._engine = None
            app.core.db._sessionmaker = None

            from app.core.db import get_db_session

            # Mock the session
            mock_session = MagicMock()

            with patch("app.core.db.get_sessionmaker") as mock_get_sm:
                mock_sm = MagicMock()
                mock_sm.return_value = mock_session
                mock_get_sm.return_value = mock_sm

                for _ in get_db_session():
                    pass

                # Session should be closed after the context manager
                mock_session.close.assert_called_once()
