import os
import logging
import stat
import posixpath  # Wichtig für die Pfad-Manipulation auf Servern
import paramiko
from wsgidav.dav_provider import DAVProvider, DAVNonCollection, DAVCollection
from wsgidav.wsgidav_app import WsgiDAVApp
from wsgidav import util
#from wsgidav.dav_error import DAVNotFoundError, DAVForbidden, DAVError
from wsgidav.dav_error import DAVError
import ssh_helper


# --- Konfiguration ---
SSH_HOST = "samson"
SSH_CONFIG_PATH = "~/.ssh/config"
REMOTE_PATH = "/tmp"
# ---------------------

# Logger für Debugging aktivieren
_logger = logging.getLogger(__name__)


class SFTPProvider(DAVProvider):
    """
    Ein WsgiDAV Provider, der ein SFTP-Backend verwendet.
    """

    def get_resource_inst(self, path: str, environ: dict):
        _logger.info(f"get_resource_inst with path: {path}, env: {environ}")
        pass

    def __init__(self):
        super().__init__()
        self.host = SSH_HOST
        self.remote_root = REMOTE_PATH

        try:
            data = ssh_helper.get_data_for_host(ssh_conf_file=SSH_CONFIG_PATH, host=self.host)
            self.port = data.get("port", "22")
            self.keyfile = os.path.expanduser(data.get("identityfile"))
            self.user = data.get("user", os.getlogin())
        except Exception as e:
            _logger.error(f"mist: {e}")

        _logger.info(f"Connecting to SFTP server {self.user}@{self.host}...")

        # Baue die SSH-Verbindung auf
        try:
            self.ssh_client = paramiko.SSHClient()
            # Host-Key automatisch akzeptieren (Riskant in Produktion! Besser Host-Keys prüfen)
            self.ssh_client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

            # Hier Logik für Key-File-Auth hinzufügen, falls 'SSH_PASS' leer ist
            self.ssh_client.connect(
                self.host,
                port=self.port,
                username=self.user,
                key_filename=self.keyfile,
                compress=True,
                timeout=10
            )
            self.sftp_client = self.ssh_client.open_sftp()
            _logger.info(f"SFTP connection established. Remote root: {self.remote_root}")

            # Testen, ob der Root-Pfad existiert
            self.sftp_client.stat(self.remote_root)

        except Exception as e:
            _logger.error(f"SFTP connection failed: {e}")
            raise

    def __del__(self):
        # Verbindung sauber schließen, wenn das Objekt zerstört wird
        if hasattr(self, 'sftp_client') and self.sftp_client:
            self.sftp_client.close()
        if hasattr(self, 'ssh_client') and self.ssh_client:
            self.ssh_client.close()
        _logger.info("SFTP connection closed.")

    def _to_remote_path(self, dav_path):
        """Übersetzt einen WebDAV-Pfad in einen SFTP-Pfad."""
        # dav_path ist z.B. "/" oder "/ordner/datei.txt"
        # posixpath.join ist wichtig, um Pfade korrekt zusammenzufügen (z.B. /root/ + /file -> /root/file)
        # und nicht z.B. // oder Windows-Backslashes zu verwenden.

        # .lstrip('/') entfernt die führende / vom dav_path, damit join korrekt funktioniert
        remote_path = posixpath.join(self.remote_root, dav_path.lstrip('/'))
        return remote_path

    def _sftp_attr_to_dav_resource(self, dav_path, attr, name):
        """Übersetzt paramiko.SFTPAttributes in eine DAV-Ressource (Datei/Ordner)."""

        # Erzeuge den vollen Pfad für diese Ressource im DAV-Namensraum
        resource_dav_path = util.join_uri(dav_path, name)

        if stat.S_ISDIR(attr.st_mode):
            # Es ist ein Verzeichnis (Collection)
            return DAVCollection(resource_dav_path, self.environ)

        # Es ist eine Datei (NonCollection)
        # Wir müssen display_name, content_length und last_modified bereitstellen
        props = {
            'display_name': name,
            'get_content_length': attr.st_size,
            'get_last_modified': attr.st_mtime,
        }
        return DAVNonCollection(resource_dav_path, self.environ, props)

    # --- Implementierung der notwendigen Provider-Methoden ---

    def get_member(self, path):
        """Gibt eine einzelne Ressource (Datei/Ordner) zurück."""
        _logger.debug(f"get_member({path})")
        remote_path = self._to_remote_path(path)

        try:
            attr = self.sftp_client.stat(remote_path)
        except FileNotFoundError:
            _logger.warning(f"get_member: {remote_path} not found")
            raise DAVError(path)
        except IOError as e:
            _logger.error(f"get_member: IOError for {remote_path}: {e}")
            raise DAVError(path)

        # Wir brauchen den Namen des Elements, nicht den ganzen Pfad
        name = posixpath.basename(path)

        # Für den Root-Pfad ("/") ist der Name leer
        if path == "/":
            name = ""
            return DAVCollection(path, self.environ)

        # Den Parent-Pfad bestimmen
        parent_path = posixpath.dirname(path)

        return self._sftp_attr_to_dav_resource(parent_path, attr, name)

    def get_member_list(self, path):
        """Listet den Inhalt eines Ordners auf."""
        _logger.debug(f"get_member_list({path})")
        remote_path = self._to_remote_path(path)

        resource_list = []
        try:
            # listdir_attr gibt eine Liste von SFTPAttributes-Objekten zurück
            for attr in self.sftp_client.listdir_attr(remote_path):
                # Ignoriere "." und ".." Einträge
                if attr.filename == "." or attr.filename == "..":
                    continue

                resource = self._sftp_attr_to_dav_resource(path, attr, attr.filename)
                resource_list.append(resource)

        except FileNotFoundError:
            _logger.warning(f"get_member_list: {remote_path} not found")
            raise DAVError(path)
        except IOError as e:
            # z.B. "Permission denied"
            _logger.error(f"get_member_list: IOError for {remote_path}: {e}")
            raise DAVError(path)

        return resource_list

    def is_read_only(self):
        """Wir wollen Schreibzugriff erlauben."""
        return False

    def create_collection(self, path):
        """Erstellt einen neuen Ordner (MKCOL)."""
        _logger.debug(f"create_collection({path})")
        remote_path = self._to_remote_path(path)

        try:
            self.sftp_client.mkdir(remote_path)
        except IOError as e:
            _logger.error(f"create_collection: Failed for {remote_path}: {e}")
            raise DAVForbidden(path)

    def get_content_stream(self, path, mode="rb"):
        """Öffnet einen Stream zum Lesen einer Datei (GET)."""
        _logger.debug(f"get_content_stream({path}, mode={mode})")
        if mode != "rb":
            raise DAVError(501, "Only read mode ('rb') is implemented for get_content_stream.")

        remote_path = self._to_remote_path(path)

        try:
            # sftp_client.open gibt ein Datei-Objekt zurück, das wsgidav lesen kann
            stream = self.sftp_client.open(remote_path, "rb")
            stream.name = path  # WsgiDav erwartet das .name Attribut
            return stream
        except FileNotFoundError:
            raise DAVNotFoundError(path)
        except IOError as e:
            _logger.error(f"get_content_stream: Failed for {remote_path}: {e}")
            raise DAVForbidden(path)

    def begin_write(self, path):
        """Öffnet einen Stream zum Schreiben einer Datei (PUT)."""
        _logger.debug(f"begin_write({path})")
        remote_path = self._to_remote_path(path)

        try:
            # Wir öffnen die Datei auf dem SFTP-Server im Schreibmodus
            stream = self.sftp_client.open(remote_path, "wb")
            return stream
        except IOError as e:
            _logger.error(f"begin_write: Failed for {remote_path}: {e}")
            raise DAVForbidden(path)

    def end_write(self, path, stream):
        """Schließt den Schreib-Stream."""
        _logger.debug(f"end_write({path})")
        # Das Stream-Objekt (vom sftp_client) muss nur geschlossen werden.
        stream.close()


# --- Hauptprogramm: Server starten ---

if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG)
    # 1. Instanziiere den Provider
    #    Der Provider stellt die Verbindung beim Start her.
    try:
        provider_instance = SFTPProvider()
    except Exception as e:
        _logger.info(f"Fehler beim Initialisieren des SFTPProviders: {e}")
        _logger.info("Bitte überprüfe die SSH_... Konfiguration oben im Skript.")
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
        },
    }

    # 3. Erstelle die WSGI-App
    app = WsgiDAVApp(config)

    # 4. Starte den Server (mit cheroot)
    _logger.info("Starte WsgiDAV-Server auf http://localhost:8080/")

    from cheroot import wsgi

    server = wsgi.Server(
        bind_addr=("localhost", 8080),
        wsgi_app=app
    )

    try:
        server.start()
    except KeyboardInterrupt:
        _logger.info("Server wird gestoppt...")
        server.stop()