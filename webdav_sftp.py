import io
import os
import logging
import stat
import posixpath
import paramiko
from contextlib import contextmanager
from dataclasses import dataclass
from queue import Queue, Empty
import threading
from wsgidav.dav_provider import DAVProvider, DAVNonCollection, DAVCollection
from wsgidav.wsgidav_app import WsgiDAVApp
from wsgidav import util
from wsgidav.dav_error import DAVError, HTTP_FORBIDDEN, HTTP_NOT_FOUND
from os.path import expanduser

import ssh_helper

_logger = logging.getLogger(__name__)


# ============================================================================
# KONFIGURATION
# ============================================================================

@dataclass
class SFTPConfig:
    """Konfiguration für SFTP-Verbindung"""
    host: str
    remote_path: str
    port: int = 22
    user: str = None
    keyfile: str = None
    pool_size: int = 3
    connection_timeout: int = 10

    @classmethod
    def from_ssh_config(cls, host: str, ssh_config_path: str = "~/.ssh/config",
                        remote_path: str = "/tmp", pool_size: int = 3):
        """Lädt Config aus SSH-Konfigurationsdatei"""
        try:
            data = ssh_helper.get_data_for_host(ssh_conf_file=ssh_config_path, host=host)
            return cls(
                host=data.get("hostname", host),
                port=int(data.get("port", "22")),
                keyfile=expanduser(data.get("identityfile")) if data.get("identityfile") else None,
                user=data.get("user", os.getenv("USER", "root")),
                remote_path=remote_path,
                pool_size=pool_size
            )
        except Exception as e:
            _logger.error(f"Fehler beim Lesen der SSH-Konfiguration: {e}")
            raise


# ============================================================================
# CONNECTION POOL
# ============================================================================

class SFTPConnectionPool:
    """Thread-sicherer Connection Pool für SFTP-Verbindungen"""

    def __init__(self, config: SFTPConfig):
        self.config = config
        self.pool = Queue(maxsize=config.pool_size)
        self.lock = threading.Lock()
        self._closed = False

        _logger.info(f"Initialisiere SFTP Connection Pool (Size: {config.pool_size})")

        # Initialisiere Pool mit Verbindungen
        for i in range(config.pool_size):
            try:
                conn = self._create_connection()
                self.pool.put(conn)
                _logger.debug(f"Connection {i + 1}/{config.pool_size} erstellt")
            except Exception as e:
                _logger.error(f"Fehler beim Erstellen von Connection {i + 1}: {e}")
                raise

    def _create_connection(self):
        """Erstellt eine neue SFTP-Verbindung"""
        ssh = paramiko.SSHClient()

        # Lade bekannte Host-Keys (sicherer als AutoAddPolicy!)
        try:
            ssh.load_host_keys(expanduser('~/.ssh/known_hosts'))
        except FileNotFoundError:
            _logger.warning("~/.ssh/known_hosts nicht gefunden. Verwende AutoAddPolicy (UNSICHER!)")
            ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())

        # Verbinde
        ssh.connect(
            self.config.host,
            port=self.config.port,
            username=self.config.user,
            key_filename=self.config.keyfile,
            compress=True,
            timeout=self.config.connection_timeout
        )

        sftp = ssh.open_sftp()

        # Aktiviere Keepalive
        transport = ssh.get_transport()
        if transport:
            transport.set_keepalive(30)

        # Validiere Remote-Path
        try:
            sftp.stat(self.config.remote_path)
        except FileNotFoundError:
            raise ValueError(f"Remote path nicht gefunden: {self.config.remote_path}")

        return sftp

    def acquire(self):
        """Entnimmt eine geprüfte Verbindung aus dem Pool. Muss mit release() zurückgegeben werden."""
        if self._closed:
            raise RuntimeError("Connection Pool wurde bereits geschlossen")

        try:
            sftp = self.pool.get(timeout=5)
        except Empty:
            _logger.error("Pool timeout - alle Verbindungen belegt")
            raise DAVError(HTTP_FORBIDDEN, "Server überlastet")

        # Teste ob Verbindung noch aktiv ist
        try:
            sftp.stat('.')
        except Exception:
            _logger.warning("Verbindung tot, erstelle neue...")
            try:
                sftp.close()
            except Exception:
                pass
            sftp = self._create_connection()

        return sftp

    def release(self, sftp):
        """Gibt eine mit acquire() entnommene Verbindung zurück in den Pool"""
        if sftp and not self._closed:
            self.pool.put(sftp)

    @contextmanager
    def get_connection(self):
        """Context Manager für sichere Verbindungs-Nutzung"""
        sftp = self.acquire()
        try:
            yield sftp
        except Exception as e:
            _logger.error(f"Fehler bei SFTP-Operation: {e}")
            # Bei Fehler: Versuche neue Verbindung zu erstellen
            try:
                sftp.close()
            except Exception:
                pass
            try:
                sftp = self._create_connection()
            except Exception as conn_error:
                _logger.error(f"Reconnect fehlgeschlagen: {conn_error}")
                sftp = None
            raise
        finally:
            self.release(sftp)

    def close(self):
        """Schließt alle Verbindungen im Pool"""
        _logger.info("Schließe Connection Pool...")
        self._closed = True

        while not self.pool.empty():
            try:
                sftp = self.pool.get_nowait()
                try:
                    sftp.close()
                except Exception:
                    pass
            except Empty:
                break


# ============================================================================
# SCHREIB-STREAM
# ============================================================================

class _SFTPWriteFile:
    """
    Wrappt einen SFTP-Filehandle, der zum Schreiben geöffnet wurde.
    Gibt die Pool-Verbindung bei close() zurück (idempotent, da WsgiDAV
    close() sowohl selbst als auch über end_write() aufrufen kann).
    """

    def __init__(self, pool, sftp, remote_file):
        self._pool = pool
        self._sftp = sftp
        self._remote_file = remote_file
        self._closed = False

    def write(self, data):
        return self._remote_file.write(data)

    def writelines(self, lines):
        return self._remote_file.writelines(lines)

    def close(self):
        if self._closed:
            return
        self._closed = True
        try:
            self._remote_file.close()
        finally:
            self._pool.release(self._sftp)


# ============================================================================
# DAV RESOURCES
# ============================================================================

class SFTPNonCollection(DAVNonCollection):
    """Datei-Ressource für WebDAV"""

    def __init__(self, path, environ, sftp_provider, file_attr):
        super().__init__(path, environ)
        self.provider = sftp_provider
        self.attr = file_attr
        self._write_file = None

    def begin_write(self, content_type=None):
        """Öffnet einen SFTP-Filehandle zum Schreiben (über den Connection Pool)"""
        self._write_file = self.provider.begin_write(self.path)
        return self._write_file

    def end_write(self, with_errors):
        """Wird von WsgiDAV nach begin_write aufgerufen (auch bei Fehlern, dann ggf. ohne close())"""
        if self._write_file is not None:
            self._write_file.close()
            self._write_file = None

    def get_content_length(self):
        return self.attr.st_size

    def get_etag(self):
        return f'{self.attr.st_size}-{int(self.attr.st_mtime)}'

    def support_etag(self):
        return True

    def get_content(self):
        return self.provider.get_content_stream(self.path, "rb")


class SFTPCollection(DAVCollection):
    """Verzeichnis-Ressource für WebDAV"""

    def __init__(self, path, environ, sftp_provider):
        super().__init__(path, environ)
        self.provider = sftp_provider

    def get_member_names(self):
        _logger.debug(f"SFTPCollection.get_member_names() for {self.path}")
        return self.provider._sftp_get_member_names(self.path)

    def get_member(self, name):
        _logger.debug(f"SFTPCollection.get_member({name}) for {self.path}")
        child_path = util.join_uri(self.path, name)
        return self.provider.get_resource_inst(child_path, self.environ)

    def create_empty_resource(self, name):
        """Erstellt eine leere Datei (für PUT auf einen bisher unbekannten Pfad)"""
        _logger.debug(f"SFTPCollection.create_empty_resource({name}) for {self.path}")
        child_path = util.join_uri(self.path, name)
        remote_path = self.provider._to_remote_path(child_path)

        try:
            with self.provider.pool.get_connection() as sftp:
                with sftp.open(remote_path, "wb"):
                    pass
        except IOError as e:
            _logger.error(f"Fehler beim Erstellen von {remote_path}: {e}")
            raise DAVError(HTTP_FORBIDDEN, str(e))

        return self.provider.get_resource_inst(child_path, self.environ)


# ============================================================================
# SFTP PROVIDER
# ============================================================================

class SFTPProvider(DAVProvider):
    """WebDAV Provider mit SFTP-Backend und Connection Pooling"""

    def __init__(self, config: SFTPConfig):
        super().__init__()
        self.config = config
        self.pool = SFTPConnectionPool(config)
        self._remote_root = posixpath.normpath(config.remote_path)
        _logger.info(f"SFTPProvider initialisiert: {config.user}@{config.host}:{config.port}")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.pool.close()

    def _to_remote_path(self, dav_path):
        """
        Konvertiert DAV-Pfad zu Remote-SFTP-Pfad.
        Lehnt Pfade ab, die '..' aus dem Remote-Root herausführen würden.
        """
        remote_path = posixpath.normpath(posixpath.join(self.config.remote_path, dav_path.lstrip('/')))

        root_prefix = self._remote_root.rstrip('/') + '/'
        if remote_path != self._remote_root and not remote_path.startswith(root_prefix):
            _logger.warning(f"Pfad-Traversal-Versuch abgewiesen: {dav_path!r} -> {remote_path!r}")
            raise DAVError(HTTP_FORBIDDEN, "Access outside root is not allowed")

        return remote_path

    def _sftp_attr_to_dav_resource(self, dav_path, attr, name, environ):
        """Konvertiert SFTP-Attribute zu DAV-Ressource"""
        resource_dav_path = util.join_uri(dav_path, name)

        if stat.S_ISDIR(attr.st_mode):
            return SFTPCollection(resource_dav_path, environ, self)

        return SFTPNonCollection(resource_dav_path, environ, self, attr)

    # ------------------------------------------------------------------------
    # Provider Interface
    # ------------------------------------------------------------------------

    def get_resource_inst(self, path: str, environ: dict):
        """
        Gibt Ressourcen-Instanz für einen Pfad zurück.
        WICHTIG: environ wird NICHT gespeichert (Race Condition vermeiden!)
        """
        _logger.debug(f"get_resource_inst({path})")
        remote_path = self._to_remote_path(path)

        try:
            with self.pool.get_connection() as sftp:
                attr = sftp.stat(remote_path)
        except FileNotFoundError:
            _logger.debug(f"Ressource nicht gefunden: {remote_path}")
            return None
        except IOError as e:
            _logger.error(f"IOError bei get_resource_inst für {remote_path}: {e}")
            raise DAVError(HTTP_FORBIDDEN, str(e))

        # Root-Verzeichnis
        if path == "/":
            return SFTPCollection(path, environ, self)

        # Alle anderen Pfade
        name = posixpath.basename(path)
        parent_path = posixpath.dirname(path)

        return self._sftp_attr_to_dav_resource(parent_path, attr, name, environ)

    def _sftp_get_member_names(self, path):
        """Gibt Liste von Dateinamen in einem Verzeichnis zurück"""
        _logger.debug(f"_sftp_get_member_names({path})")
        remote_path = self._to_remote_path(path)

        try:
            with self.pool.get_connection() as sftp:
                names = []
                for attr in sftp.listdir_attr(remote_path):
                    if attr.filename not in (".", ".."):
                        names.append(attr.filename)
                return names
        except FileNotFoundError:
            _logger.warning(f"Verzeichnis nicht gefunden: {remote_path}")
            raise DAVError(HTTP_NOT_FOUND, f"Path not found: {path}")
        except IOError as e:
            _logger.error(f"IOError bei _sftp_get_member_names für {remote_path}: {e}")
            raise DAVError(HTTP_FORBIDDEN, str(e))

    def is_read_only(self):
        return False

    def create_collection(self, path):
        """Erstellt ein Verzeichnis"""
        _logger.debug(f"create_collection({path})")
        remote_path = self._to_remote_path(path)

        try:
            with self.pool.get_connection() as sftp:
                sftp.mkdir(remote_path)
        except IOError as e:
            _logger.error(f"Fehler beim Erstellen von {remote_path}: {e}")
            raise DAVError(HTTP_FORBIDDEN, str(e))

    def delete(self, path):
        """Löscht Datei oder Verzeichnis (rekursiv)"""
        with self.pool.get_connection() as sftp:
            self._delete(sftp, path)

    def _delete(self, sftp, path):
        """Löscht Datei oder Verzeichnis (rekursiv) über eine bereits offene Verbindung"""
        _logger.debug(f"delete({path})")
        remote_path = self._to_remote_path(path)

        try:
            attr = sftp.stat(remote_path)

            if stat.S_ISDIR(attr.st_mode):
                _logger.debug(f"Lösche Verzeichnis rekursiv: {remote_path}")
                self._sftp_delete_recursive(sftp, remote_path)
            else:
                _logger.debug(f"Lösche Datei: {remote_path}")
                sftp.remove(remote_path)
        except FileNotFoundError:
            _logger.warning(f"Zu löschendes Element nicht gefunden: {remote_path}")
            raise DAVError(HTTP_NOT_FOUND, f"Path not found: {path}")
        except IOError as e:
            _logger.error(f"Fehler beim Löschen von {remote_path}: {e}")
            raise DAVError(HTTP_FORBIDDEN, str(e))

    def move(self, src_path, dest_path, overwrite):
        """Verschiebt/Benennt Datei oder Verzeichnis um"""
        _logger.debug(f"move({src_path} -> {dest_path}, overwrite={overwrite})")
        remote_src = self._to_remote_path(src_path)
        remote_dest = self._to_remote_path(dest_path)

        with self.pool.get_connection() as sftp:
            try:
                # Prüfe ob Ziel existiert
                sftp.stat(remote_dest)
                if not overwrite:
                    raise DAVError(412, "Destination exists and overwrite=False")
                # Lösche Ziel
                _logger.debug(f"Ziel existiert, lösche: {remote_dest}")
                self._delete(sftp, dest_path)
            except FileNotFoundError:
                pass  # Ziel existiert nicht - OK

            try:
                sftp.rename(remote_src, remote_dest)
            except FileNotFoundError:
                raise DAVError(HTTP_NOT_FOUND, f"Source not found: {src_path}")
            except IOError as e:
                _logger.error(f"Move fehlgeschlagen: {e}")
                raise DAVError(HTTP_FORBIDDEN, str(e))

    def copy(self, src_path, dest_path, overwrite, depth):
        """Kopiert Datei oder Verzeichnis"""
        _logger.debug(f"copy({src_path} -> {dest_path}, overwrite={overwrite}, depth={depth})")

        if depth not in ("0", "infinity"):
            raise DAVError(501, "Only depth '0' and 'infinity' supported")

        remote_src = self._to_remote_path(src_path)
        remote_dest = self._to_remote_path(dest_path)

        with self.pool.get_connection() as sftp:
            # Prüfe ob Ziel existiert
            try:
                sftp.stat(remote_dest)
                if not overwrite:
                    raise DAVError(412, "Destination exists and overwrite=False")
                self._delete(sftp, dest_path)
            except FileNotFoundError:
                pass

            try:
                src_attr = sftp.stat(remote_src)

                if stat.S_ISDIR(src_attr.st_mode):
                    if depth != "infinity":
                        raise DAVError(400, "COPY on collection requires depth='infinity'")
                    _logger.debug(f"Kopiere Verzeichnis rekursiv: {remote_src}")
                    self._sftp_copy_recursive(sftp, remote_src, remote_dest)
                else:
                    _logger.debug(f"Kopiere Datei: {remote_src}")
                    self._sftp_copy_file(sftp, remote_src, remote_dest)
            except FileNotFoundError:
                raise DAVError(HTTP_NOT_FOUND, f"Source not found: {src_path}")
            except Exception as e:
                _logger.error(f"Copy fehlgeschlagen: {e}")
                raise DAVError(HTTP_FORBIDDEN, str(e))

    def get_content_stream(self, path, mode="rb"):
        """Gibt Dateiinhalt als BytesIO-Stream zurück"""
        _logger.debug(f"get_content_stream({path})")

        if mode != "rb":
            raise DAVError(501, "Only 'rb' mode supported")

        remote_path = self._to_remote_path(path)

        try:
            with self.pool.get_connection() as sftp:
                with sftp.open(remote_path, "rb") as f:
                    data = f.read()

            stream = io.BytesIO(data)
            stream.name = path
            return stream
        except FileNotFoundError:
            raise DAVError(HTTP_NOT_FOUND, f"File not found: {path}")
        except IOError as e:
            _logger.error(f"Fehler beim Lesen von {remote_path}: {e}")
            raise DAVError(HTTP_FORBIDDEN, str(e))

    def begin_write(self, path):
        """
        Öffnet einen SFTP-Filehandle zum direkten Schreiben.
        Die Pool-Verbindung wird bis close() gehalten und danach zurückgegeben.
        """
        _logger.debug(f"begin_write({path})")
        remote_path = self._to_remote_path(path)

        sftp = self.pool.acquire()
        try:
            remote_file = sftp.open(remote_path, "wb")
        except IOError as e:
            self.pool.release(sftp)
            _logger.error(f"Fehler beim Öffnen von {remote_path} zum Schreiben: {e}")
            raise DAVError(HTTP_FORBIDDEN, str(e))

        return _SFTPWriteFile(self.pool, sftp, remote_file)

    # ------------------------------------------------------------------------
    # Hilfsmethoden
    # ------------------------------------------------------------------------

    def _sftp_delete_recursive(self, sftp, remote_dir_path):
        """Löscht Verzeichnis rekursiv"""
        try:
            for attr in sftp.listdir_attr(remote_dir_path):
                if attr.filename in ('.', '..'):
                    continue

                item_path = posixpath.join(remote_dir_path, attr.filename)

                if stat.S_ISDIR(attr.st_mode):
                    self._sftp_delete_recursive(sftp, item_path)
                else:
                    sftp.remove(item_path)

            sftp.rmdir(remote_dir_path)
        except Exception as e:
            _logger.error(f"Rekursives Löschen fehlgeschlagen für {remote_dir_path}: {e}")
            raise

    def _sftp_copy_file(self, sftp, remote_src, remote_dest):
        """Kopiert einzelne Datei"""
        try:
            with sftp.open(remote_src, 'rb') as f_src:
                data = f_src.read()

            with sftp.open(remote_dest, 'wb') as f_dest:
                f_dest.write(data)

            # Kopiere Permissions
            attr = sftp.stat(remote_src)
            sftp.chmod(remote_dest, attr.st_mode)
        except Exception as e:
            _logger.error(f"Datei-Copy fehlgeschlagen: {remote_src} -> {remote_dest}: {e}")
            raise

    def _sftp_copy_recursive(self, sftp, remote_src_dir, remote_dest_dir):
        """Kopiert Verzeichnis rekursiv"""
        try:
            # Erstelle Zielverzeichnis
            sftp.mkdir(remote_dest_dir)

            # Kopiere Permissions
            attr_src = sftp.stat(remote_src_dir)
            sftp.chmod(remote_dest_dir, attr_src.st_mode)
        except IOError as e:
            _logger.warning(f"Verzeichnis {remote_dest_dir} existiert bereits: {e}")

        # Kopiere Inhalte
        for attr in sftp.listdir_attr(remote_src_dir):
            if attr.filename in ('.', '..'):
                continue

            src_item = posixpath.join(remote_src_dir, attr.filename)
            dest_item = posixpath.join(remote_dest_dir, attr.filename)

            if stat.S_ISDIR(attr.st_mode):
                self._sftp_copy_recursive(sftp, src_item, dest_item)
            else:
                self._sftp_copy_file(sftp, src_item, dest_item)


# ============================================================================
# HAUPTPROGRAMM
# ============================================================================

if __name__ == "__main__":
    logging.basicConfig(
        level=logging.DEBUG,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

    try:
        # Lade Konfiguration
        config = SFTPConfig.from_ssh_config(
            host="samson",
            ssh_config_path="~/.ssh/config",
            remote_path="/tmp",
            pool_size=3
        )

        # Erstelle Provider
        provider = SFTPProvider(config)

    except Exception as e:
        _logger.critical(f"Fehler beim Initialisieren: {e}")
        _logger.critical("Bitte SSH-Konfiguration überprüfen!")
        exit(1)

    # Ab hier ist der Pool offen - garantiert schließen, egal wie die
    # Server-Ausführung endet (Ctrl+C, Bind-Fehler, unerwartete Exception).
    with provider:
        # Konfiguriere WsgiDAV
        webdav_config = {
            "provider_mapping": {
                "/": provider,
            },
            "http_authenticator": {
                "domain_controller": None  # Keine WebDAV-Auth
            },
            "simple_dc": {
                "user_mapping": {
                    "*": True  # ⚠️ ACHTUNG: Jeder hat Zugriff!
                }
            },
            "verbose": 3,
            "logging": {
                "enable": True,
                "enable_loggers": [],
            }
        }

        app = WsgiDAVApp(webdav_config)

        _logger.info("=" * 60)
        _logger.info("WebDAV-SFTP Server gestartet")
        _logger.info("URL: http://localhost:8080/")
        _logger.info(f"Backend: {config.user}@{config.host}:{config.remote_path}")
        _logger.info(f"Connection Pool: {config.pool_size} Verbindungen")
        _logger.info("=" * 60)

        from cheroot import wsgi

        server = wsgi.Server(
            bind_addr=("localhost", 8080),
            wsgi_app=app,
            numthreads=10  # Unterstützt bis zu 10 parallele Requests
        )

        try:
            server.start()
        except KeyboardInterrupt:
            _logger.info("Server wird gestoppt...")
        finally:
            server.stop()
            _logger.info("Auf Wiedersehen!")
