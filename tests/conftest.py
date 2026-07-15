import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import webdav_sftp as wds  # noqa: E402
from fake_sftp import FakeSFTP  # noqa: E402

REMOTE_ROOT = "/remote/webdav"


@pytest.fixture
def fake_sftp():
    return FakeSFTP(dirs={REMOTE_ROOT})


@pytest.fixture
def make_provider(fake_sftp):
    """Baut einen SFTPProvider, dessen Connection-Pool ausschließlich die
    übergebene FakeSFTP-Instanz ausgibt - kein echtes SSH nötig."""

    def _make(pool_size=2, remote_path=REMOTE_ROOT, logger=None):
        with patch.object(wds.SFTPConnectionPool, "_create_connection", return_value=fake_sftp):
            config = wds.SFTPConfig(host="dummy", remote_path=remote_path, pool_size=pool_size)
            return wds.SFTPProvider(config, logger=logger)

    return _make


@pytest.fixture
def provider(make_provider):
    p = make_provider()
    yield p
    p.pool.close()


@pytest.fixture
def environ(provider):
    """Minimales WSGI-environ, wie es DAVProvider/DAVResource benoetigen."""
    return {"wsgidav.provider": provider}
