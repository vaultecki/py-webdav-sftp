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


def mount_drive(letter, port, timeout=15):
    """
    Bindet http://localhost:<port>/ als Laufwerk <letter>: ein.
    Gibt bei Erfolg True zurück, sonst False. Fehler werden geloggt statt
    geworfen - ein fehlgeschlagenes Auto-Mount soll den WebDAV-Server nicht
    als 'nicht gestartet' erscheinen lassen (manuelles Mounten bleibt möglich).
    """
    if not letter:
        return False
    if not IS_WINDOWS:
        _logger.warning("Auto-Mount wird nur unter Windows unterstützt, überspringe.")
        return False

    letter = letter.rstrip(":").upper()
    unc_path = rf"\\localhost@{port}\DavWWWRoot"

    try:
        result = subprocess.run(
            ["net", "use", f"{letter}:", unc_path, "/persistent:no"],
            capture_output=True, text=True, timeout=timeout,
        )
    except (subprocess.TimeoutExpired, OSError) as e:
        _logger.warning(f"Laufwerk {letter}: konnte nicht gemountet werden: {e}")
        return False

    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip()
        _logger.warning(f"Laufwerk {letter}: konnte nicht gemountet werden ({detail})")
        return False

    _logger.info(f"Laufwerk {letter}: erfolgreich auf {unc_path} gemountet")
    return True


def unmount_drive(letter, timeout=15):
    """Trennt ein zuvor mit mount_drive() eingebundenes Laufwerk wieder."""
    if not letter or not IS_WINDOWS:
        return False

    letter = letter.rstrip(":").upper()

    try:
        result = subprocess.run(
            ["net", "use", f"{letter}:", "/delete", "/y"],
            capture_output=True, text=True, timeout=timeout,
        )
    except (subprocess.TimeoutExpired, OSError) as e:
        _logger.warning(f"Laufwerk {letter}: konnte nicht getrennt werden: {e}")
        return False

    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip()
        _logger.warning(f"Laufwerk {letter}: konnte nicht getrennt werden ({detail})")
        return False

    _logger.info(f"Laufwerk {letter}: getrennt")
    return True
