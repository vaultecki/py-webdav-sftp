"""In-memory Fake für paramiko.SFTPClient - genug Oberfläche für die Tests von webdav_sftp.py"""
import io
import stat as stat_module
from dataclasses import dataclass


@dataclass
class FakeAttr:
    st_mode: int
    st_size: int = 0
    st_mtime: float = 0.0


@dataclass
class FakeDirEntry:
    filename: str
    st_mode: int


class _FakeSFTPFile(io.BytesIO):
    """BytesIO, das beim close() den Inhalt zurück ins Fake-Dateisystem schreibt."""

    def __init__(self, fs, path, writing, initial=b""):
        super().__init__(initial)
        self._fs = fs
        self._path = path
        self._writing = writing

    def close(self):
        if self._writing:
            self._fs.files[self._path] = self.getvalue()
        super().close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()


class FakeSFTP:
    """Simuliert genug von paramiko.SFTPClient, um SFTPProvider ohne echtes SSH zu testen."""

    def __init__(self, dirs=None, files=None):
        self.dirs = set(dirs or set())
        self.files = dict(files or {})
        self.closed = False

    def stat(self, path):
        if path == ".":
            return FakeAttr(st_mode=stat_module.S_IFDIR)
        if path in self.dirs:
            return FakeAttr(st_mode=stat_module.S_IFDIR)
        if path in self.files:
            return FakeAttr(st_mode=stat_module.S_IFREG, st_size=len(self.files[path]))
        raise FileNotFoundError(path)

    def listdir_attr(self, path):
        prefix = path.rstrip("/") + "/"
        names = set()
        for p in list(self.dirs) + list(self.files):
            if p.startswith(prefix):
                rest = p[len(prefix):]
                if rest and "/" not in rest:
                    names.add(rest)
        return [FakeDirEntry(filename=name, st_mode=self.stat(prefix + name).st_mode)
                for name in sorted(names)]

    def mkdir(self, path):
        if path in self.dirs or path in self.files:
            raise IOError(f"{path} existiert bereits")
        self.dirs.add(path)

    def rmdir(self, path):
        if path not in self.dirs:
            raise FileNotFoundError(path)
        self.dirs.discard(path)

    def remove(self, path):
        if path not in self.files:
            raise FileNotFoundError(path)
        del self.files[path]

    def rename(self, src, dst):
        if src in self.files:
            self.files[dst] = self.files.pop(src)
        elif src in self.dirs:
            self.dirs.discard(src)
            self.dirs.add(dst)
        else:
            raise FileNotFoundError(src)

    def chmod(self, path, mode):
        pass

    def open(self, path, mode="r"):
        writing = "w" in mode or "a" in mode
        if writing:
            initial = self.files.get(path, b"") if "a" in mode else b""
            return _FakeSFTPFile(self, path, writing=True, initial=initial)
        if path not in self.files:
            raise FileNotFoundError(path)
        return _FakeSFTPFile(self, path, writing=False, initial=self.files[path])

    def close(self):
        self.closed = True
