from conftest import REMOTE_ROOT


def test_put_overwrites_existing_file(provider, fake_sftp, environ):
    """Regressionstest fuer den 'hope to fix write error'-Bug: end_write()
    war ein No-Op-Stub, Upload-Daten wurden stillschweigend verworfen."""
    fake_sftp.files[f"{REMOTE_ROOT}/file.txt"] = b"old content"

    resource = provider.get_resource_inst("/file.txt", environ)
    assert resource is not None

    # Simuliert exakt den Ablauf aus wsgidav/request_server.py:
    # fileobj = res.begin_write(...); fileobj.write(...); fileobj.close();
    # res.end_write(...)
    stream = resource.begin_write(content_type="text/plain")
    stream.write(b"new content")
    stream.close()
    resource.end_write(with_errors=False)

    assert fake_sftp.files[f"{REMOTE_ROOT}/file.txt"] == b"new content"


def test_put_creates_new_file_via_create_empty_resource(provider, fake_sftp, environ):
    """Regressionstest: create_empty_resource fehlte komplett, PUT auf einen
    neuen Pfad scheiterte mit 403, bevor ueberhaupt begin_write erreicht wurde."""
    root_resource = provider.get_resource_inst("/", environ)
    new_resource = root_resource.create_empty_resource("new.txt")

    assert f"{REMOTE_ROOT}/new.txt" in fake_sftp.files
    assert fake_sftp.files[f"{REMOTE_ROOT}/new.txt"] == b""

    stream = new_resource.begin_write(content_type="text/plain")
    stream.write(b"hello world")
    stream.close()
    new_resource.end_write(with_errors=False)

    assert fake_sftp.files[f"{REMOTE_ROOT}/new.txt"] == b"hello world"


def test_write_releases_pool_connection(provider, fake_sftp, environ):
    """begin_write() haelt die Pool-Connection bis close() - danach muss sie
    zurueck sein."""
    resource = provider.get_resource_inst("/", environ)
    empty = resource.create_empty_resource("x.txt")
    # unveraendert nach create_empty_resource (with-Block)
    assert provider.pool.pool.qsize() == 2

    stream = empty.begin_write()
    # Connection ist waehrend des Schreibens ausgecheckt
    assert provider.pool.pool.qsize() == 1

    stream.close()
    assert provider.pool.pool.qsize() == 2  # sofort nach close() zurueck im Pool

    # end_write() ruft close() erneut auf - muss idempotent sein
    empty.end_write(with_errors=False)
    assert provider.pool.pool.qsize() == 2


def test_end_write_closes_stream_if_write_failed_before_close(
    provider, fake_sftp, environ
):
    """Wenn der Body-Transfer fehlschlaegt, ruft wsgidav.request_server.py
    res.end_write(with_errors=True) auf, OHNE vorher fileobj.close() zu rufen.
    Die Connection darf dabei nicht im Pool verloren gehen."""
    resource = provider.get_resource_inst("/", environ)
    empty = resource.create_empty_resource("y.txt")

    empty.begin_write()
    assert provider.pool.pool.qsize() == 1

    empty.end_write(with_errors=True)
    assert provider.pool.pool.qsize() == 2
