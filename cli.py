#!/usr/bin/env python3
"""
Kommandozeilen-Version von PyDAVSFTP - startet den WebDAV-SFTP-Server ohne GUI.
Geeignet für Scripting, Server-Deployments oder Autostart (z.B. via
Windows-Aufgabenplanung oder systemd), wo keine Tkinter-Oberfläche gewünscht ist.
"""
import argparse
import logging
import signal
import sys

from cheroot import wsgi
from wsgidav.wsgidav_app import WsgiDAVApp

import windows_mount
from webdav_sftp import SFTPConfig, SFTPProvider

_logger = logging.getLogger(__name__)


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        prog="pydavsftp",
        description="WebDAV-Server mit SFTP-Backend - verbindet einen entfernten "
                     "SSH/SFTP-Server per WebDAV (z.B. als Laufwerk in Windows).",
    )
    parser.add_argument(
        "--host", required=True,
        help="Host-Name aus der SSH-Config (z.B. 'myserver' aus ~/.ssh/config)",
    )
    parser.add_argument(
        "--ssh-config", default="~/.ssh/config",
        help="Pfad zur SSH-Config-Datei (Default: ~/.ssh/config)",
    )
    parser.add_argument(
        "--remote-path", default="/tmp",
        help="Freizugebendes Verzeichnis auf dem Remote-Server (Default: /tmp)",
    )
    parser.add_argument(
        "--port", type=int, default=8080,
        help="WebDAV-Port, an localhost gebunden (Default: 8080)",
    )
    parser.add_argument(
        "--pool-size", type=int, default=3,
        help="Anzahl paralleler SFTP-Verbindungen im Pool (Default: 3)",
    )
    parser.add_argument(
        "--connection-timeout", type=int, default=10,
        help="SSH-Verbindungs-Timeout in Sekunden (Default: 10)",
    )
    parser.add_argument(
        "--drive-letter", default=None, metavar="LETTER",
        help="Windows: Laufwerksbuchstabe zum automatischen Einbinden per 'net use' "
             "(z.B. X). Wirkungslos auf anderen Betriebssystemen.",
    )
    parser.add_argument(
        "--log-level", default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Log-Level (Default: INFO)",
    )
    return parser.parse_args(argv)


def run(args):
    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    try:
        config = SFTPConfig.from_ssh_config(
            host=args.host,
            ssh_config_path=args.ssh_config,
            remote_path=args.remote_path,
            pool_size=args.pool_size,
        )
        config.connection_timeout = args.connection_timeout
    except Exception as e:
        _logger.critical(f"Fehler beim Initialisieren: {e}")
        _logger.critical("Bitte SSH-Konfiguration überprüfen!")
        return 1

    # Ab hier ist der Pool offen - garantiert schließen, egal wie der Server endet.
    with SFTPProvider(config) as provider:
        webdav_config = {
            "provider_mapping": {
                "/": provider,
            },
            "http_authenticator": {
                "domain_controller": None  # Keine WebDAV-Auth
            },
            "simple_dc": {
                "user_mapping": {
                    "*": True  # Nur relevant, falls doch mal Auth aktiviert wird
                }
            },
            "verbose": 1,
            "logging": {
                "enable": True,
                "enable_loggers": [],
            },
        }

        app = WsgiDAVApp(webdav_config)

        server = wsgi.Server(
            bind_addr=("localhost", args.port),
            wsgi_app=app,
            numthreads=10,
        )

        # prepare() bindet den Socket - erst danach ist der Server erreichbar
        # und ein Auto-Mount unter Windows kann sinnvoll versucht werden.
        server.prepare()

        _logger.info("=" * 60)
        _logger.info("WebDAV-SFTP Server gestartet")
        _logger.info(f"URL: http://localhost:{args.port}/")
        _logger.info(f"Backend: {config.user}@{config.host}:{config.remote_path}")
        _logger.info(f"Connection Pool: {config.pool_size} Verbindungen")
        _logger.info("=" * 60)

        mounted = False
        if args.drive_letter:
            mounted = windows_mount.mount_drive(args.drive_letter, args.port)

        def handle_sigterm(signum, frame):
            raise KeyboardInterrupt()

        signal.signal(signal.SIGTERM, handle_sigterm)

        try:
            server.serve()
        except KeyboardInterrupt:
            _logger.info("Server wird gestoppt...")
        finally:
            if mounted:
                windows_mount.unmount_drive(args.drive_letter)
            server.stop()
            _logger.info("Auf Wiedersehen!")

    return 0


def main(argv=None):
    args = parse_args(argv)
    return run(args)


if __name__ == "__main__":
    sys.exit(main())
