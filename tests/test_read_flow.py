import io

import pytest
from wsgidav.dav_error import DAVError

from conftest import REMOTE_ROOT


def test_get_content_streams_full_file(provider, fake_sftp, environ):
    fake_sftp.files[f"{REMOTE_ROOT}/file.txt"] = b"hello world"

    resource = provider.get_resource_inst("/file.txt", environ)
    stream = resource.get_content()
    try:
        assert stream.name == "/file.txt"
        assert stream.read(5) == b"hello"
        assert stream.read() == b" world"
    finally:
        stream.close()


def test_get_content_supports_seek_for_range_requests(provider, fake_sftp, environ):
    """wsgidav.request_server.py ruft vor dem Lesen fileobj.seek(range_start) auf."""
    fake_sftp.files[f"{REMOTE_ROOT}/file.txt"] = b"0123456789"

    resource = provider.get_resource_inst("/file.txt", environ)
    stream = resource.get_content()
    try:
        stream.seek(5)
        assert stream.read(3) == b"567"
    finally:
        stream.close()


def test_get_content_returns_streaming_wrapper_not_bytesio(provider, fake_sftp, environ):
    """Regressionstest: get_content_stream() lud frueher die komplette Datei
    per f.read() in einen BytesIO-Puffer, bevor irgendein Byte zurueckgegeben
    wurde. Jetzt wird direkt vom offenen SFTP-Handle gelesen."""
    fake_sftp.files[f"{REMOTE_ROOT}/file.txt"] = b"x" * 1000

    resource = provider.get_resource_inst("/file.txt", environ)
    stream = resource.get_content()
    try:
        assert not isinstance(stream, io.BytesIO)
        assert stream.read(10) == b"x" * 10
    finally:
        stream.close()


def test_get_content_releases_pool_connection_on_close(provider, fake_sftp, environ):
    fake_sftp.files[f"{REMOTE_ROOT}/file.txt"] = b"data"

    resource = provider.get_resource_inst("/file.txt", environ)
    assert provider.pool.pool.qsize() == 2

    stream = resource.get_content()
    assert provider.pool.pool.qsize() == 1  # Connection waehrend des Lesens ausgecheckt

    stream.close()
    assert provider.pool.pool.qsize() == 2

    stream.close()  # muss idempotent sein
    assert provider.pool.pool.qsize() == 2


def test_get_content_missing_file_raises_and_releases_connection(provider):
    assert provider.pool.pool.qsize() == 2

    with pytest.raises(DAVError):
        provider.get_content_stream("/missing.txt")

    assert provider.pool.pool.qsize() == 2  # Connection trotz Fehler zurueckgegeben
