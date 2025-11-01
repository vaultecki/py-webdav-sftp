import os
import logging
import stat
import posixpath
import paramiko
# DAVNonCollection ist OK, aber DAVCollection ist jetzt abstrakt
from wsgidav.dav_provider import DAVProvider, DAVNonCollection, DAVCollection
from wsgidav.wsgidav_app import WsgiDAVApp
from wsgidav import util
#from wsgidav.dav_error import DAVNotFoundError, DAVForbidden, DAVError, DAVError_PreconditionFailed
from wsgidav.dav_error import DAVError

import ssh_helper

# --- Konfiguration ---
SSH_HOST = "samson"
SSH_CONFIG_PATH = "~/.ssh/config"
REMOTE_PATH = "/tmp"

_logger = logging.getLogger(__name__)


class SFTPNonCollection(DAVNonCollection):
    """
    Implementiert die Datei-Logik für WsgiDAV v4.
    MUSS alle abstrakten Methoden implementieren.
    """
    def __init__(self, path, environ, sftp_provider, file_attr):
        super().__init__(path, environ)
        self.provider = sftp_provider
        self.attr = file_attr

    # Implementierung der abstrakten Methoden:

    def get_content_length(self):
        """Gibt die Dateigröße zurück."""
        return self.attr.st_size

    def get_etag(self):
        """Erzeugt einen einfachen ETag aus Größe und Änderungszeit."""
        # WsgiDAV benötigt ein ETag für Caching und If-Match-Header.
        # Ein einfacher ETag ist ausreichend.
        return f'"{self.attr.st_size}-{self.attr.st_mtime}"'

    def support_etag(self):
        """Gibt an, dass ETag unterstützt wird."""
        return True

    def get_content(self):
        """
        Gibt den Inhalt der Datei als Byte-Stream zurück.
        Wird für kleine Dateien benötigt.
        Wir delegieren dies an den Provider.
        """
        return self.provider.get_content_stream(self.path, "rb")


class SFTPCollection(DAVCollection):
    """
    Implementiert die Verzeichnis-Logik für WsgiDAV v4.
    Diese Klasse MUSS get_member_names() und get_member() implementieren.
    """

    def __init__(self, path, environ, sftp_provider):
        # Wir übergeben den Provider an die Basisklasse
        super().__init__(path, environ)
        self.provider = sftp_provider  # (self.provider wird von der Basisklasse gesetzt)

    def get_member_names(self):
        """Gibt eine Liste von Namen (str) im Verzeichnis zurück."""
        _logger.debug(f"SFTPCollection.get_member_names() for path {self.path}")
        # Ruft die neue Helfermethode auf dem Provider auf
        return self.provider._sftp_get_member_names(self.path)

    def get_member(self, name):
        """Gibt ein einzelnes Kind-Objekt (DAVResource) zurück."""
        _logger.debug(f"SFTPCollection.get_member(name={name}) for path {self.path}")
        # Ruft die Haupt-Factory-Methode des Providers auf
        child_path = util.join_uri(self.path, name)
        return self.provider.get_resource_inst(child_path, self.environ)


# ---------------------------------------------------------------------

class SFTPProvider(DAVProvider):

    # ... (__init__, __del__, _to_remote_path bleiben gleich) ...
    def __init__(self):
        super().__init__()
        self.host = SSH_HOST
        self.remote_root = REMOTE_PATH
        try:
            data = ssh_helper.get_data_for_host(ssh_conf_file=SSH_CONFIG_PATH, host=self.host)
            self.port = int(data.get("port", "22"))
            self.keyfile = os.path.expanduser(data.get("identityfile"))
            self.user = data.get("user", os.getlogin())
        except Exception as e:
            _logger.error(f"Fehler beim Lesen der SSH-Konfiguration: {e}")
            raise
        _logger.info(f"Connecting to SFTP server {self.user}@{self.host}:{self.port}...")
        try:
            self.ssh_client = paramiko.SSHClient()
            #self.ssh_client.load_system_host_keys()
            # Host-Key automatisch akzeptieren (Riskant in Produktion! Besser Host-Keys prüfen)
            self.ssh_client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            self.ssh_client.connect(
                self.host, port=self.port, username=self.user,
                key_filename=self.keyfile, compress=True, timeout=10
            )
            self.sftp_client = self.ssh_client.open_sftp()
            _logger.info(f"SFTP connection established. Remote root: {self.remote_root}")
            self.sftp_client.stat(self.remote_root)
        except Exception as e:
            _logger.error(f"SFTP connection failed: {e}")
            raise

    def __del__(self):
        if hasattr(self, 'sftp_client') and self.sftp_client: self.sftp_client.close()
        if hasattr(self, 'ssh_client') and self.ssh_client: self.ssh_client.close()
        _logger.info("SFTP connection closed.")

    def _to_remote_path(self, dav_path):
        return posixpath.join(self.remote_root, dav_path.lstrip('/'))

    def _sftp_attr_to_dav_resource(self, dav_path, attr, name):
        """
        (ANGEPASST) Übersetzt SFTPAttributes in eine DAV-Ressource.
        Verwendet jetzt SFTPNonCollection statt DAVNonCollection.
        """
        resource_dav_path = util.join_uri(dav_path, name)

        if stat.S_ISDIR(attr.st_mode):
            return SFTPCollection(resource_dav_path, self.environ, self)

        # HIER DIE ÄNDERUNG: Jetzt unsere neue Klasse verwenden
        # Wir übergeben die SFTP-Attribute (attr), die wir später brauchen
        return SFTPNonCollection(resource_dav_path, self.environ, self, attr)

    # --- Implementierung der Provider-Methoden ---

    def get_resource_inst(self, path: str, environ: dict):
        """
        (ANGEPASST) Gibt eine Ressourcen-Instanz für einen Pfad zurück.
        """
        _logger.debug(f"get_resource_inst({path})")
        # Speichere die Umgebung
        self.environ = environ
        remote_path = self._to_remote_path(path)

        try:
            attr = self.sftp_client.stat(remote_path)
        except FileNotFoundError:
            _logger.debug(f"get_resource_inst: {remote_path} not found")
            return None
        except IOError as e:
            _logger.error(f"get_resource_inst: IOError for {remote_path}: {e}")
            raise DAVForbidden(path)

        # Für den Root-Pfad ("/")
        if path == "/":
            # HIER DIE ÄNDERUNG:
            return SFTPCollection(path, self.environ, self)

        # Für alle anderen Pfade
        name = posixpath.basename(path)
        parent_path = posixpath.dirname(path)

        return self._sftp_attr_to_dav_resource(parent_path, attr, name)

    def _sftp_get_member_names(self, path):
        """
        (NEUE HELFERMETHODE)
        Ersetzt die Logik der alten get_member_list.
        Gibt nur eine Liste von Namen (str) zurück.
        """
        _logger.debug(f"_sftp_get_member_names({path})")
        remote_path = self._to_remote_path(path)
        name_list = []
        try:
            for attr in self.sftp_client.listdir_attr(remote_path):
                if attr.filename == "." or attr.filename == "..":
                    continue
                name_list.append(attr.filename)

        except FileNotFoundError:
            _logger.warning(f"_sftp_get_member_names: {remote_path} not found")
            raise DAVNotFoundError(path)
        except IOError as e:
            _logger.error(f"_sftp_get_member_names: IOError for {remote_path}: {e}")
            raise DAVForbidden(path)

        return name_list

    # -----------------------------------------------------------------
    # ENTFERNT: get_member_list(self, path)
    # Diese Logik befindet sich jetzt in _sftp_get_member_names
    # und wird von SFTPCollection.get_member_names() aufgerufen.
    # -----------------------------------------------------------------

    def is_read_only(self):
        return False

    # ... (Alle anderen Methoden: create_collection, delete, move, copy,
    #      get_content_stream, begin_write, end_write,
    #      _sftp_delete_recursive, _sftp_copy_file, _sftp_copy_recursive
    #      bleiben exakt gleich wie in deiner letzten Version.) ...

    def create_collection(self, path):
        _logger.debug(f"create_collection({path})")
        remote_path = self._to_remote_path(path)
        try:
            self.sftp_client.mkdir(remote_path)
        except IOError as e:
            _logger.error(f"create_collection: Failed for {remote_path}: {e}")
            raise DAVForbidden(path)

    def delete(self, path):
        _logger.debug(f"delete({path})")
        remote_path = self._to_remote_path(path)
        try:
            attr = self.sftp_client.stat(remote_path)
            if stat.S_ISDIR(attr.st_mode):
                _logger.debug(f"Recursively deleting directory: {remote_path}")
                self._sftp_delete_recursive(remote_path)
            else:
                _logger.debug(f"Deleting file: {remote_path}")
                self.sftp_client.remove(remote_path)
        except FileNotFoundError:
            _logger.warning(f"delete: {remote_path} not found")
            raise DAVNotFoundError(path)
        except IOError as e:
            _logger.error(f"delete: Failed for {remote_path}: {e}")
            raise DAVForbidden(path)

    def move(self, src_path, dest_path, overwrite):
        _logger.debug(f"move({src_path}, {dest_path}, overwrite={overwrite})")
        remote_src = self._to_remote_path(src_path)
        remote_dest = self._to_remote_path(dest_path)
        try:
            self.sftp_client.stat(remote_dest)
            if not overwrite:
                _logger.warning("Move failed: Destination exists and overwrite=False")
                raise DAVError_PreconditionFailed("Destination already exists.")
            _logger.debug(f"Move: destination {remote_dest} exists, deleting it first.")
            self.delete(dest_path)
        except FileNotFoundError:
            pass
        except Exception as e:
            _logger.error(f"Move: failed checking/deleting destination {remote_dest}: {e}")
            raise DAVForbidden(f"Move failed: {e}")
        try:
            self.sftp_client.rename(remote_src, remote_dest)
        except FileNotFoundError:
            _logger.error(f"Move: source {remote_src} not found")
            raise DAVNotFoundError(src_path)
        except IOError as e:
            _logger.error(f"Move: rename {remote_src} to {remote_dest} failed: {e}")
            raise DAVForbidden(f"Move failed: {e}")

    def copy(self, src_path, dest_path, overwrite, depth):
        _logger.debug(f"copy({src_path}, {dest_path}, overwrite={overwrite}, depth={depth})")
        if depth not in ("0", "infinity"):
            raise DAVError(501, "Only '0' and 'infinity' depth COPY is supported.")
        remote_src = self._to_remote_path(src_path)
        remote_dest = self._to_remote_path(dest_path)
        try:
            self.sftp_client.stat(remote_dest)
            if not overwrite:
                _logger.warning("Copy failed: Destination exists and overwrite=False")
                raise DAVError_PreconditionFailed("Destination already exists.")
            _logger.debug(f"Copy: destination {remote_dest} exists, deleting it first.")
            self.delete(dest_path)
        except FileNotFoundError:
            pass
        except Exception as e:
            _logger.error(f"Copy: failed checking/deleting destination {remote_dest}: {e}")
            raise DAVForbidden(f"Copy failed: {e}")
        try:
            src_attr = self.sftp_client.stat(remote_src)
            if stat.S_ISDIR(src_attr.st_mode):
                if depth != "infinity":
                    raise DAVError(400, "COPY with depth='0' on a collection is not supported.")
                _logger.debug(f"Recursively copying directory {remote_src} to {remote_dest}")
                self._sftp_copy_recursive(remote_src, remote_dest)
            else:
                _logger.debug(f"Copying file {remote_src} to {remote_dest}")
                self._sftp_copy_file(remote_src, remote_dest)
        except FileNotFoundError:
            _logger.error(f"Copy: source {remote_src} not found")
            raise DAVNotFoundError(src_path)
        except Exception as e:
            _logger.error(f"Copy: operation failed: {e}")
            raise DAVForbidden(f"Copy failed: {e}")

    def get_content_stream(self, path, mode="rb"):
        _logger.debug(f"get_content_stream({path}, mode={mode})")
        if mode != "rb":
            raise DAVError(501, "Only read mode ('rb') is implemented.")
        remote_path = self._to_remote_path(path)
        try:
            stream = self.sftp_client.open(remote_path, "rb")
            stream.name = path
            return stream
        except FileNotFoundError:
            raise DAVNotFoundError(path)
        except IOError as e:
            _logger.error(f"get_content_stream: Failed for {remote_path}: {e}")
            raise DAVForbidden(path)

    def begin_write(self, path):
        _logger.debug(f"begin_write({path})")
        remote_path = self._to_remote_path(path)
        try:
            stream = self.sftp_client.open(remote_path, "wb")
            return stream
        except IOError as e:
            _logger.error(f"begin_write: Failed for {remote_path}: {e}")
            raise DAVForbidden(path)

    def end_write(self, path, stream):
        _logger.debug(f"end_write({path})")
        stream.close()

    def _sftp_delete_recursive(self, remote_dir_path):
        try:
            for attr in self.sftp_client.listdir_attr(remote_dir_path):
                if attr.filename == '.' or attr.filename == '..': continue
                item_path = posixpath.join(remote_dir_path, attr.filename)
                if stat.S_ISDIR(attr.st_mode):
                    self._sftp_delete_recursive(item_path)
                else:
                    self.sftp_client.remove(item_path)
            self.sftp_client.rmdir(remote_dir_path)
        except Exception as e:
            _logger.error(f"Failed recursive delete on {remote_dir_path}: {e}")
            raise DAVForbidden(f"Recursive delete failed: {e}")

    def _sftp_copy_file(self, remote_src, remote_dest):
        try:
            with self.sftp_client.open(remote_src, 'rb') as f_src:
                data = f_src.read()
            with self.sftp_client.open(remote_dest, 'wb') as f_dest:
                f_dest.write(data)
            attr = self.sftp_client.stat(remote_src)
            self.sftp_client.chmod(remote_dest, attr.st_mode)
        except Exception as e:
            _logger.error(f"Failed to copy file {remote_src} to {remote_dest}: {e}")
            raise

    def _sftp_copy_recursive(self, remote_src_dir, remote_dest_dir):
        try:
            self.sftp_client.mkdir(remote_dest_dir)
            attr_src = self.sftp_client.stat(remote_src_dir)
            self.sftp_client.chmod(remote_dest_dir, attr_src.st_mode)
        except IOError as e:
            _logger.warning(f"Could not mkdir {remote_dest_dir} (may already exist): {e}")
        for attr in self.sftp_client.listdir_attr(remote_src_dir):
            if attr.filename == '.' or attr.filename == '..': continue
            src_item_path = posixpath.join(remote_src_dir, attr.filename)
            dest_item_path = posixpath.join(remote_dest_dir, attr.filename)
            if stat.S_ISDIR(attr.st_mode):
                self._sftp_copy_recursive(src_item_path, dest_item_path)
            else:
                self._sftp_copy_file(src_item_path, dest_item_path)


# --- (Hauptprogramm bleibt gleich) ---

if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG)

    try:
        provider_instance = SFTPProvider()
    except Exception as e:
        _logger.critical(f"Fehler beim Initialisieren des SFTPProviders: {e}")
        _logger.critical("Bitte überprüfe die SSH-Konfiguration und die Verbindung.")
        exit(1)

    # 2. Konfiguriere den WsgiDavApp-Server
    config = {
        "provider_mapping": {
            "/": provider_instance,  # Mappe den DAV-Root "/" auf unseren SFTPProvider
        },
        "http_authenticator": {
            "domain_controller": None  # Keine WebDAV-Authentifizierung (einfachster Fall)
        },
        "simple_dc": {
            "user_mapping": {
                "*": True  # Erlaube allen anonymen Zugriff
            }
        },
        "verbose": 3,  # 0=quiet, 1=normal, 2=info, 3=debug
        "logging": {
            "enable": True,
            "enable_loggers": [],  # Leere Liste -> Aktiviere alle Logger
        }
    }
    app = WsgiDAVApp(config)
    _logger.info("Starte WsgiDAV-Server auf http://localhost:8080/")
    from cheroot import wsgi

    server = wsgi.Server(bind_addr=("localhost", 8080), wsgi_app=app)
    try:
        server.start()
    except KeyboardInterrupt:
        _logger.info("Server wird gestoppt...")
        server.stop()
