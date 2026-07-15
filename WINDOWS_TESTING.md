# Windows-Testcheckliste

Manueller Testplan für Funktionen, die von hier aus (Linux, kein Windows verfügbar)
nicht automatisiert getestet werden konnten: GUI-Rendering, `net use`-Verhalten,
Windows-Explorer-Integration. Ca. 15-20 Minuten.

Voraussetzungen: Windows-Rechner (Client-Edition, kein Server ohne WebClient-Feature),
Python 3.8+, Zugriff auf einen echten SSH/SFTP-Server zum Testen.

## 0. Setup

- [ ] `pip install -r requirements.txt` läuft ohne Fehler durch
- [ ] `~/.ssh/config` enthält einen Test-Host mit funktionierendem Key-Login
- [ ] `ssh <host>` funktioniert manuell in der Kommandozeile (Key-Auth, keine Passwortabfrage)

## 1. GUI - Grundfunktion

- [ ] `python main.py` startet, Fenster öffnet sich ohne Exceptions in der Konsole
- [ ] SSH-Config-Pfad wird korrekt vorbefüllt, "Laden" zeigt Hosts aus der Config im Dropdown
- [ ] Host auswählen, Remote-Path setzen (z.B. ein Testverzeichnis mit ein paar Dateien), "Starten" klicken
- [ ] Status wechselt Gestoppt → Verbinde... → Läuft (grün)
- [ ] Log-Fenster zeigt Verbindungsaufbau-Meldungen

## 2. GUI - Auto-Mount (Laufwerksbuchstabe)

- [ ] Dropdown "Laufwerk (Windows)" zeigt Buchstaben D-Z + "Deaktiviert" zur Auswahl
- [ ] Buchstaben auswählen, der noch nicht belegt ist (z.B. `X`), Server starten
- [ ] Log zeigt `Laufwerk X: erfolgreich auf \\localhost@<port>\DavWWWRoot gemountet`
- [ ] Explorer öffnen → Laufwerk `X:` ist da und zeigt den Remote-Path-Inhalt
- [ ] "Stoppen" klicken → Log zeigt `Laufwerk X: getrennt`
- [ ] Explorer: Laufwerk `X:` ist verschwunden (nicht nur "nicht erreichbar", sondern wirklich weg aus "Dieser PC")
- [ ] **Fehlerfall**: Laufwerk `X:` manuell schon anderweitig belegen (z.B. `net use X: \\anderer-pfad`), dann Server mit `X` starten → Server startet trotzdem erfolgreich (Status "Läuft"), Log zeigt eine Warnung statt eines Absturzes. Danach `net use X: /delete` zum Aufräumen.

## 3. Dateioperationen über das gemountete Laufwerk

Alles über den Explorer auf `X:`, nicht über SFTP direkt - wir testen den WebDAV-Pfad.

- [ ] Bestehende Datei öffnen (z.B. Textdatei in Editor) - Inhalt korrekt
- [ ] Neue Datei erstellen (Rechtsklick → Neu → Textdokument), Inhalt reinschreiben, speichern, schließen, wieder öffnen - Inhalt ist da (das ist der Bug, den wir in dieser Session gefixt haben - hier zeigt sich ob der Fix wirklich greift)
- [ ] Bestehende Datei überschreiben/speichern (in Editor ändern, speichern) - Änderung bleibt erhalten
- [ ] Datei umbenennen
- [ ] Datei in Unterordner verschieben (drag&drop)
- [ ] Datei kopieren (Strg+C/Strg+V) in denselben oder anderen Ordner
- [ ] Ordner anlegen
- [ ] Datei/Ordner löschen
- [ ] Eine Datei >50 MB kopieren → erwartet: schlägt fehl (bekanntes `WebClient`-Limit, siehe README). Falls das getestet werden soll ohne den Fehler: `FileSizeLimitInBytes` per Registry hochsetzen (siehe README-Troubleshooting), `WebClient`-Dienst neu starten, erneut versuchen

## 4. CLI

- [ ] `python cli.py --help` zeigt alle Optionen
- [ ] `python cli.py --host <host> --remote-path <pfad> --drive-letter X` startet, Log zeigt Mount-Erfolg
- [ ] Laufwerk `X:` im Explorer sichtbar, Dateizugriff funktioniert (wie oben, reicht ein Kurztest: eine Datei lesen und eine schreiben)
- [ ] `Strg+C` im Terminal → Server stoppt sauber, Log zeigt `Server wird gestoppt...` / `Auf Wiedersehen!`, Laufwerk `X:` ist danach weg

## 5. Autostart (GUI)

- [ ] "Autostart" aktivieren, Konfiguration speichern, Anwendung schließen und neu starten
- [ ] Server startet automatisch, Fenster minimiert sich, Laufwerk wird automatisch gemountet

## Ergebnis

Kurz hier eintragen (oder als Notiz zurückmelden), was nicht wie erwartet lief:

```
Datum:
Windows-Version:
Auffälligkeiten:
```
