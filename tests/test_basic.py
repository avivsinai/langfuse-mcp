"""Basic tests for langfuse-mcp package."""

import importlib
import logging
import os
import sys
from unittest.mock import MagicMock

import pytest


def test_configure_logging_console():
    """configure_logging should honor log level and console flag."""
    from langfuse_mcp.__main__ import configure_logging

    configure_logging("DEBUG", True)
    root_handlers = logging.getLogger().handlers
    assert logging.getLogger().level == logging.DEBUG
    assert any(isinstance(handler, logging.StreamHandler) for handler in root_handlers)


def test_cli_env_defaults(monkeypatch):
    """Environment variables should provide defaults for CLI flags."""
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "env-pk")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "env-sk")
    monkeypatch.setenv("LANGFUSE_HOST", "https://env-host")
    monkeypatch.setenv("LANGFUSE_LOG_LEVEL", "DEBUG")
    monkeypatch.setenv("LANGFUSE_LOG_TO_CONSOLE", "true")
    monkeypatch.setenv("LANGFUSE_MCP_DEFAULT_OUTPUT_MODE", "full_json_file")

    from langfuse_mcp.__main__ import _build_arg_parser, _read_env_defaults

    parser = _build_arg_parser(_read_env_defaults())
    args = parser.parse_args([])

    assert args.public_key == "env-pk"
    assert args.secret_key == "env-sk"
    assert args.host == "https://env-host"
    assert args.log_level == "DEBUG"
    assert args.log_to_console is True
    assert args.default_output_mode == "full_json_file"


def test_max_age_days_env_override(monkeypatch):
    """LANGFUSE_MAX_AGE_DAYS should configure the lookback cap at import time."""
    import langfuse_mcp.__main__ as main_module

    original_env_value = os.environ.get("LANGFUSE_MAX_AGE_DAYS")
    try:
        monkeypatch.setenv("LANGFUSE_MAX_AGE_DAYS", "30")
        reloaded = importlib.reload(main_module)

        assert reloaded.MAX_AGE_DAYS == 30
        assert reloaded.MAX_AGE_MINUTES == 30 * reloaded.DAY
        assert "max 30 days/43200 minutes" in reloaded.AGE_LOOKBACK_DESCRIPTION
        assert reloaded.validate_age(30 * reloaded.DAY) == 30 * reloaded.DAY
    finally:
        if original_env_value is None:
            monkeypatch.delenv("LANGFUSE_MAX_AGE_DAYS", raising=False)
        else:
            monkeypatch.setenv("LANGFUSE_MAX_AGE_DAYS", original_env_value)
        importlib.reload(main_module)


def test_cli_accepts_no_keys_without_env(monkeypatch):
    """Keys are optional — credentials can be supplied per-request via HTTP headers."""
    monkeypatch.delenv("LANGFUSE_PUBLIC_KEY", raising=False)
    monkeypatch.delenv("LANGFUSE_SECRET_KEY", raising=False)
    monkeypatch.delenv("LANGFUSE_LOG_LEVEL", raising=False)
    monkeypatch.delenv("LANGFUSE_LOG_TO_CONSOLE", raising=False)
    monkeypatch.delenv("LANGFUSE_HOST", raising=False)

    from langfuse_mcp.__main__ import _build_arg_parser, _read_env_defaults

    parser = _build_arg_parser(_read_env_defaults())
    args = parser.parse_args([])
    assert args.public_key is None
    assert args.secret_key is None


def test_package_importable():
    """Test that the package can be imported."""
    # This test verifies the package can be imported
    try:
        import langfuse_mcp

        assert langfuse_mcp.__version__ is not None
    except ImportError:
        pytest.fail("Failed to import langfuse_mcp package")


def test_main_module_importable():
    """Test that the main module can be imported."""
    # This test verifies the main module can be imported
    try:
        # Use pytest.importorskip instead of direct import
        pytest.importorskip("langfuse_mcp.__main__")
    except ImportError:
        pytest.fail("Failed to import langfuse_mcp.__main__ module")


def test_python_version():
    """Test that Python version is compatible."""
    # This test verifies we're running on a compatible Python version
    # (our package requires Python 3.10+)
    python_version = sys.version_info
    assert python_version.major == 3
    assert python_version.minor >= 10, f"Python version {python_version.major}.{python_version.minor} is not supported"


# ---------------------------------------------------------------------------
# _BoundedClientCache
# ---------------------------------------------------------------------------


class TestBoundedClientCache:
    """Tests for the bounded LRU cache used to hold per-request Langfuse clients."""

    def _make_cache(self, maxsize: int = 2):
        from langfuse_mcp.__main__ import _BoundedClientCache

        return _BoundedClientCache(maxsize=maxsize)

    def test_never_exceeds_maxsize(self):
        """Cache length must never exceed maxsize regardless of insertion count."""
        maxsize = 5
        cache = self._make_cache(maxsize)
        for i in range(maxsize + 10):
            cache[(f"pk_{i}", f"sk_{i}")] = MagicMock()
        assert len(cache) <= maxsize

    def test_lru_eviction_flushes_and_shuts_down_client(self):
        """The LRU client must be flushed and shut down when it is evicted."""
        cache = self._make_cache(maxsize=2)
        client_a = MagicMock()
        client_b = MagicMock()
        client_c = MagicMock()

        cache[("pk_a", "sk_a")] = client_a
        cache[("pk_b", "sk_b")] = client_b
        # Access client_a to promote it — client_b becomes LRU
        _ = cache[("pk_a", "sk_a")]
        # Inserting client_c must evict client_b (LRU)
        cache[("pk_c", "sk_c")] = client_c

        client_b.flush.assert_called_once()
        client_b.shutdown.assert_called_once()
        # client_a and client_c must not be touched
        client_a.flush.assert_not_called()
        client_c.flush.assert_not_called()

    def test_evicted_key_removed_from_cache(self):
        """After eviction the key must no longer be present in the cache."""
        cache = self._make_cache(maxsize=2)
        cache[("pk_a", "sk_a")] = MagicMock()
        cache[("pk_b", "sk_b")] = MagicMock()
        # Access a so b is LRU; inserting c evicts b
        _ = cache[("pk_a", "sk_a")]
        cache[("pk_c", "sk_c")] = MagicMock()

        assert ("pk_b", "sk_b") not in cache
        assert ("pk_a", "sk_a") in cache
        assert ("pk_c", "sk_c") in cache

    def test_no_eviction_below_maxsize(self):
        """Clients must not be flushed or shut down before the cache is full."""
        cache = self._make_cache(maxsize=3)
        clients = [MagicMock() for _ in range(3)]
        for i, client in enumerate(clients):
            cache[(f"pk_{i}", f"sk_{i}")] = client

        for client in clients:
            client.flush.assert_not_called()
            client.shutdown.assert_not_called()


# ---------------------------------------------------------------------------
# bind_host default
# ---------------------------------------------------------------------------


def test_bind_host_default_is_localhost(monkeypatch):
    """--bind-host must default to 127.0.0.1, not 0.0.0.0."""
    monkeypatch.delenv("LANGFUSE_MCP_BIND_HOST", raising=False)
    from langfuse_mcp.__main__ import _build_arg_parser, _read_env_defaults

    parser = _build_arg_parser(_read_env_defaults())
    args = parser.parse_args([])
    assert args.bind_host == "127.0.0.1"
