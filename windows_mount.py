"""
Bindet den laufenden WebDAV-Server unter Windows automatisch als
Laufwerksbuchstaben ein (über den WebDAV-Redirector via 'net use').
Auf anderen Betriebssystemen sind alle Funktionen No-Ops.
"""
import logging
import platform
import subprocess

_logger = logging.getLogger(__name__)

IS_WINDOWS = platform.system() == "Windows"


def _ensure_webclient_running(log):
    """
    Startet den 'WebClient'-Dienst (WebDAV-Redirector) explizit vor.
    Er ist standardmäßig als 'Manual (Trigger Start)' konfiguriert und wird
    sonst erst durch den net-use-Aufruf selbst gestartet - dieser Kaltstart
    kann mehrere Sekunden dauern und lässt net use sonst ins Timeout laufen.
    Fehler hier sind nicht fatal, net use liefert danach ohnehin eine
    aussagekräftige eigene Fehlermeldung (z.B. wenn der Dienst fehlt).
    """
    try:
        subprocess.run(
            ["sc", "start", "WebClient"],
            capture_output=True, text=True, timeout=10, stdin=subprocess.DEVNULL,
        )
    except (subprocess.TimeoutExpired, OSError) as e:
        log.debug(f"WebClient-Dienst konnte nicht vorab gestartet werden: {e}")


def mount_drive(letter, port, timeout=30, logger=None):
    """
    Bindet http://localhost:<port>/ als Laufwerk <letter>: ein.
    Gibt bei Erfolg True zurück, sonst False. Fehler werden geloggt statt
    geworfen - ein fehlgeschlagenes Auto-Mount soll den WebDAV-Server nicht
    als 'nicht gestartet' erscheinen lassen (manuelles Mounten bleibt möglich).
    """
    log = logger or _logger

    if not letter:
        return False
    if not IS_WINDOWS:
        log.warning("Auto-Mount wird nur unter Windows unterstützt, überspringe.")
        return False

    letter = letter.rstrip(":").upper()
    url = f"http://localhost:{port}"

    _ensure_webclient_running(log)

    try:
        result = subprocess.run(
            ["net", "use", f"{letter}:", url, "/persistent:no"],
            capture_output=True, text=True, timeout=timeout,
            stdin=subprocess.DEVNULL,
        )
    except (subprocess.TimeoutExpired, OSError) as e:
        log.warning(f"Laufwerk {letter}: konnte nicht gemountet werden: {e}")
        return False

    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip()
        log.warning(f"Laufwerk {letter}: konnte nicht gemountet werden ({detail})")
        return False

    log.info(f"Laufwerk {letter}: erfolgreich auf {url} gemountet")
    return True


def unmount_drive(letter, timeout=15, logger=None):
    """Trennt ein zuvor mit mount_drive() eingebundenes Laufwerk wieder."""
    log = logger or _logger

    if not letter or not IS_WINDOWS:
        return False

    letter = letter.rstrip(":").upper()

    try:
        result = subprocess.run(
            ["net", "use", f"{letter}:", "/delete", "/y"],
            capture_output=True, text=True, timeout=timeout,
            stdin=subprocess.DEVNULL,
        )
    except (subprocess.TimeoutExpired, OSError) as e:
        log.warning(f"Laufwerk {letter}: konnte nicht getrennt werden: {e}")
        return False

    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip()
        log.warning(f"Laufwerk {letter}: konnte nicht getrennt werden ({detail})")
        return False

    log.info(f"Laufwerk {letter}: getrennt")
    return True
