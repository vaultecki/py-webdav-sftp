import threading
import time

from conftest import REMOTE_ROOT


def test_acquire_release_roundtrip(provider, fake_sftp):
    sftp = provider.pool.acquire()
    assert sftp is fake_sftp
    provider.pool.release(sftp)

    sftp2 = provider.pool.acquire()
    assert sftp2 is fake_sftp
    provider.pool.release(sftp2)


def test_move_with_overwrite_does_not_deadlock_with_pool_size_one(
    make_provider, fake_sftp
):
    """Regressionstest: move() rief früher self.delete() auf, während die
    eigene Pool-Connection noch gehalten wurde - bei pool_size=1 blockierte
    das 5s und scheiterte dann mit 'Server ueberlastet'."""
    fake_sftp.files[f"{REMOTE_ROOT}/src.txt"] = b"hello"
    fake_sftp.files[f"{REMOTE_ROOT}/dest.txt"] = b"old"

    provider = make_provider(pool_size=1)
    try:
        result = {}

        def run():
            provider.move("/src.txt", "/dest.txt", overwrite=True)
            result["done"] = True

        t = threading.Thread(target=run, daemon=True)
        start = time.monotonic()
        t.start()
        t.join(timeout=2)  # deutlich unter dem 5s Pool-Timeout
        elapsed = time.monotonic() - start

        assert result.get(
            "done"
        ), "move() ist nicht rechtzeitig fertig geworden - Deadlock?"
        assert elapsed < 2
        assert fake_sftp.files[f"{REMOTE_ROOT}/dest.txt"] == b"hello"
        assert f"{REMOTE_ROOT}/src.txt" not in fake_sftp.files
    finally:
        provider.pool.close()


def test_copy_with_overwrite_does_not_deadlock_with_pool_size_one(
    make_provider, fake_sftp
):
    fake_sftp.files[f"{REMOTE_ROOT}/src.txt"] = b"hello"
    fake_sftp.files[f"{REMOTE_ROOT}/dest.txt"] = b"old"

    provider = make_provider(pool_size=1)
    try:
        result = {}

        def run():
            provider.copy("/src.txt", "/dest.txt", overwrite=True, depth="0")
            result["done"] = True

        t = threading.Thread(target=run, daemon=True)
        t.start()
        t.join(timeout=2)

        assert result.get(
            "done"
        ), "copy() ist nicht rechtzeitig fertig geworden - Deadlock?"
        assert fake_sftp.files[f"{REMOTE_ROOT}/dest.txt"] == b"hello"
        # Quelle bleibt bei copy erhalten
        assert fake_sftp.files[f"{REMOTE_ROOT}/src.txt"] == b"hello"
    finally:
        provider.pool.close()
