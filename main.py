import itertools
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import logging
import threading
from os.path import expanduser

from config_manager import ConfigManager
from webdav_sftp import SFTPConfig, SFTPProvider
from wsgidav.wsgidav_app import WsgiDAVApp
from cheroot import wsgi
import ssh_helper
import windows_mount

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

DRIVE_LETTER_DISABLED = "Deaktiviert"
DRIVE_LETTER_CHOICES = [DRIVE_LETTER_DISABLED] + [chr(c) for c in range(ord("D"), ord("Z") + 1)]

DEFAULT_CONNECTION = {
    "ssh_config_file": "~/.ssh/config",
    "host": "",
    "remote_path": "/tmp",
    "pool_size": 3,
    "webdav_port": 8080,
    "drive_letter": "",
    "autostart": False,
}


class TextHandler(logging.Handler):
    """Log-Handler, der Meldungen in ein Tkinter-Text-Widget schreibt."""

    def __init__(self, text_widget):
        super().__init__()
        self.text_widget = text_widget

    def emit(self, record):
        msg = self.format(record)

        def append():
            try:
                self.text_widget.config(state="normal")
                self.text_widget.insert("end", msg + "\n")
                self.text_widget.see("end")
                self.text_widget.config(state="disabled")
            except tk.TclError:
                # Widget wurde bereits zerstört (z.B. Log-Eintrag eines
                # Hintergrund-Threads nach dem Schließen des Fensters/Tabs)
                pass

        try:
            self.text_widget.after(0, append)
        except RuntimeError:
            # Tk-Mainloop läuft nicht mehr
            pass


class WebDAVServerThread(threading.Thread):
    """Thread für einen einzelnen WebDAV-Server"""

    def __init__(self, config, webdav_port, drive_letter=None, error_callback=None, logger=None):
        super().__init__(daemon=True)
        self.config = config
        self.webdav_port = webdav_port
        self.drive_letter = drive_letter
        self.server = None
        self.provider = None
        self._stop_event = threading.Event()
        self.error_callback = error_callback
        self.started = False
        self.mounted = False
        self.logger = logger or logging.getLogger(__name__)

    def run(self):
        try:
            # Erstelle Provider (kann SSH-Fehler werfen)
            self.logger.info("Erstelle SFTP-Verbindungen...")
            self.provider = SFTPProvider(self.config, logger=self.logger)

            # Konfiguriere WsgiDAV
            webdav_config = {
                "provider_mapping": {
                    "/": self.provider,
                },
                "http_authenticator": {
                    "domain_controller": None
                },
                "simple_dc": {
                    "user_mapping": {
                        "*": True
                    }
                },
                "verbose": 1,
                "logging": {
                    "enable": True,
                    "enable_loggers": [],
                }
            }

            app = WsgiDAVApp(webdav_config)

            self.server = wsgi.Server(
                bind_addr=("localhost", self.webdav_port),
                wsgi_app=app,
                numthreads=10
            )

            # prepare() bindet den Socket bereits - erst danach ist der
            # Server unter dem Port wirklich erreichbar (start() = prepare() + serve()).
            self.server.prepare()
            self.started = True
            self.logger.info(f"WebDAV Server gestartet auf Port {self.webdav_port}")

            if self.drive_letter:
                self.mounted = windows_mount.mount_drive(self.drive_letter, self.webdav_port, logger=self.logger)

            self.server.serve()

        except Exception as e:
            self.logger.error(f"Fehler beim Starten des Servers: {e}")
            # Falls Laufwerk/Pool schon aufgebaut wurden, bevor der Fehler
            # auftrat (z.B. Server stürzt waehrend serve() ab): nichts offen
            # bzw. gemountet hängen lassen.
            if self.mounted:
                windows_mount.unmount_drive(self.drive_letter, logger=self.logger)
                self.mounted = False
            if self.provider:
                self.provider.pool.close()
            if self.error_callback:
                self.error_callback(str(e))

    def stop(self):
        """Stoppt den Server"""
        if self.mounted:
            windows_mount.unmount_drive(self.drive_letter, logger=self.logger)
            self.mounted = False
        if self.server:
            self.logger.info("Stoppe WebDAV Server...")
            self.server.stop()
        if self.provider:
            self.provider.pool.close()
        self._stop_event.set()


class ConnectionTab:
    """Eine einzelne WebDAV/SFTP-Verbindung mit eigener UI, eigenem
    Server-Thread und eigenem Log - entspricht einem Tab im Notebook."""

    _id_counter = itertools.count(1)

    def __init__(self, notebook, config_dict=None):
        self.id = next(ConnectionTab._id_counter)
        self.notebook = notebook
        self.frame = ttk.Frame(notebook)
        self.logger = logging.getLogger(f"connection.{self.id}")

        self.server_thread = None
        self.is_running = False
        self.log_handler = None

        self._create_widgets()
        self._load_from_dict(config_dict or DEFAULT_CONNECTION)

        self.notebook.add(self.frame, text=self.tab_title())
        self.host_var.trace_add("write", lambda *_: self._update_tab_title())

    # ------------------------------------------------------------------------
    # UI-Aufbau
    # ------------------------------------------------------------------------

    def _create_widgets(self):
        root = self.frame

        # === Status-Frame ===
        status_frame = ttk.LabelFrame(root, text="Server Status", padding=10)
        status_frame.pack(fill="x", padx=10, pady=5)

        self.status_label = ttk.Label(
            status_frame, text="● Gestoppt", font=("Arial", 12, "bold"), foreground="red"
        )
        self.status_label.pack(side="left", padx=5)

        self.start_button = ttk.Button(status_frame, text="Starten", command=self.toggle_server, width=15)
        self.start_button.pack(side="right", padx=5)

        # === SSH Config Frame ===
        ssh_frame = ttk.LabelFrame(root, text="SSH Konfiguration", padding=10)
        ssh_frame.pack(fill="x", padx=10, pady=5)

        ttk.Label(ssh_frame, text="SSH Config Datei:").grid(row=0, column=0, sticky="w", pady=2)
        config_row = ttk.Frame(ssh_frame)
        config_row.grid(row=0, column=1, sticky="ew", pady=2)

        self.ssh_config_var = tk.StringVar(value="~/.ssh/config")
        ttk.Entry(config_row, textvariable=self.ssh_config_var).pack(side="left", fill="x", expand=True)
        ttk.Button(config_row, text="...", width=3, command=self.browse_ssh_config).pack(side="right", padx=(5, 0))

        ttk.Label(ssh_frame, text="Host:").grid(row=1, column=0, sticky="w", pady=2)
        host_row = ttk.Frame(ssh_frame)
        host_row.grid(row=1, column=1, sticky="ew", pady=2)

        self.host_var = tk.StringVar()
        self.host_combo = ttk.Combobox(host_row, textvariable=self.host_var, state="readonly")
        self.host_combo.pack(side="left", fill="x", expand=True)
        ttk.Button(host_row, text="Laden", command=self.load_ssh_hosts).pack(side="right", padx=(5, 0))

        ttk.Label(ssh_frame, text="Remote Path:").grid(row=2, column=0, sticky="w", pady=2)
        self.remote_path_var = tk.StringVar(value="/tmp")
        ttk.Entry(ssh_frame, textvariable=self.remote_path_var).grid(row=2, column=1, sticky="ew", pady=2)

        ttk.Label(ssh_frame, text="Pool Size:").grid(row=3, column=0, sticky="w", pady=2)
        self.pool_size_var = tk.IntVar(value=3)
        ttk.Spinbox(ssh_frame, from_=1, to=10, textvariable=self.pool_size_var, width=10).grid(
            row=3, column=1, sticky="w", pady=2
        )

        ssh_frame.columnconfigure(1, weight=1)

        # === WebDAV Config Frame ===
        webdav_frame = ttk.LabelFrame(root, text="WebDAV Konfiguration", padding=10)
        webdav_frame.pack(fill="x", padx=10, pady=5)

        ttk.Label(webdav_frame, text="Port:").grid(row=0, column=0, sticky="w", pady=2)
        self.webdav_port_var = tk.IntVar(value=8080)
        ttk.Spinbox(webdav_frame, from_=1024, to=65535, textvariable=self.webdav_port_var, width=10).grid(
            row=0, column=1, sticky="w", pady=2
        )

        ttk.Label(webdav_frame, text="Laufwerk (Windows):").grid(row=1, column=0, sticky="w", pady=2)
        self.drive_letter_var = tk.StringVar(value=DRIVE_LETTER_DISABLED)
        ttk.Combobox(
            webdav_frame,
            textvariable=self.drive_letter_var,
            values=DRIVE_LETTER_CHOICES,
            state="readonly",
            width=12,
        ).grid(row=1, column=1, sticky="w", pady=2)

        webdav_frame.columnconfigure(1, weight=1)

        # === Einstellungen Frame ===
        settings_frame = ttk.LabelFrame(root, text="Einstellungen", padding=10)
        settings_frame.pack(fill="x", padx=10, pady=5)

        self.autostart_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            settings_frame,
            text="Autostart (mit der Anwendung automatisch starten)",
            variable=self.autostart_var
        ).pack(anchor="w")

        # === Log Frame ===
        log_frame = ttk.LabelFrame(root, text="Log", padding=10)
        log_frame.pack(fill="both", expand=True, padx=10, pady=5)

        self.log_text = tk.Text(log_frame, height=8, state="disabled", wrap="word")
        self.log_text.pack(side="left", fill="both", expand=True)

        scrollbar = ttk.Scrollbar(log_frame, command=self.log_text.yview)
        scrollbar.pack(side="right", fill="y")
        self.log_text.config(yscrollcommand=scrollbar.set)

        self._setup_log_handler()

    def _setup_log_handler(self):
        """Hängt einen TextHandler an den Tab-eigenen Logger (nicht den Root-Logger),
        damit jeder Tab nur seine eigenen Meldungen sieht."""
        self.log_handler = TextHandler(self.log_text)
        self.log_handler.setFormatter(
            logging.Formatter('%(asctime)s - %(levelname)s - %(message)s', datefmt='%H:%M:%S'))
        self.logger.addHandler(self.log_handler)

    def remove_log_handler(self):
        if self.log_handler is not None:
            self.logger.removeHandler(self.log_handler)
            self.log_handler = None

    # ------------------------------------------------------------------------
    # Tab-Verwaltung
    # ------------------------------------------------------------------------

    def tab_title(self):
        host = self.host_var.get().strip()
        return host if host else f"Verbindung {self.id}"

    def _update_tab_title(self):
        try:
            self.notebook.tab(self.frame, text=self.tab_title())
        except tk.TclError:
            pass

    # ------------------------------------------------------------------------
    # Konfiguration
    # ------------------------------------------------------------------------

    def to_dict(self):
        drive_letter = self.drive_letter_var.get()
        return {
            "ssh_config_file": self.ssh_config_var.get(),
            "host": self.host_var.get(),
            "remote_path": self.remote_path_var.get(),
            "pool_size": self.pool_size_var.get(),
            "webdav_port": self.webdav_port_var.get(),
            "drive_letter": "" if drive_letter == DRIVE_LETTER_DISABLED else drive_letter,
            "autostart": self.autostart_var.get(),
        }

    def _load_from_dict(self, d):
        self.ssh_config_var.set(d.get("ssh_config_file", "~/.ssh/config"))
        self.host_var.set(d.get("host", ""))
        self.remote_path_var.set(d.get("remote_path", "/tmp"))
        self.pool_size_var.set(d.get("pool_size", 3))
        self.webdav_port_var.set(d.get("webdav_port", 8080))
        self.drive_letter_var.set(d.get("drive_letter", "") or DRIVE_LETTER_DISABLED)
        self.autostart_var.set(d.get("autostart", False))

        if self.ssh_config_var.get():
            self.load_ssh_hosts()

    def browse_ssh_config(self):
        """Öffnet Dateidialog für SSH Config"""
        filename = filedialog.askopenfilename(
            title="SSH Config Datei auswählen",
            initialdir=expanduser("~/.ssh"),
            filetypes=[("Config files", "config"), ("All files", "*.*")]
        )
        if filename:
            self.ssh_config_var.set(filename)
            self.load_ssh_hosts()

    def load_ssh_hosts(self):
        """Lädt verfügbare Hosts aus SSH Config"""
        try:
            ssh_config_path = expanduser(self.ssh_config_var.get())
            hosts = ssh_helper.get_hosts(ssh_config_path)

            self.host_combo['values'] = hosts
            if hosts and not self.host_var.get():
                self.host_combo.current(0)

            self.log(f"✓ {len(hosts)} Hosts geladen")

        except Exception as e:
            self.log(f"✗ Fehler beim Laden der Hosts: {e}", "ERROR")
            messagebox.showerror("Fehler", f"SSH Config konnte nicht geladen werden:\n{e}")

    # ------------------------------------------------------------------------
    # Server-Steuerung
    # ------------------------------------------------------------------------

    def toggle_server(self):
        if self.is_running:
            self.stop_server()
        else:
            self.start_server()

    def start_server(self):
        """Startet den WebDAV-Server für diese Verbindung"""
        try:
            if not self.host_var.get():
                messagebox.showerror("Fehler", "Bitte Host auswählen!")
                return

            sftp_config = SFTPConfig.from_ssh_config(
                host=self.host_var.get(),
                ssh_config_path=expanduser(self.ssh_config_var.get()),
                remote_path=self.remote_path_var.get(),
                pool_size=self.pool_size_var.get(),
                logger=self.logger,
            )

            self.is_running = True
            self.status_label.config(text="● Verbinde...", foreground="orange")
            self.start_button.config(text="Stoppen", state="disabled")
            self.log("⏳ Starte Server, baue SSH-Verbindungen auf...")

            drive_letter = self.drive_letter_var.get()
            self.server_thread = WebDAVServerThread(
                sftp_config,
                self.webdav_port_var.get(),
                drive_letter=None if drive_letter == DRIVE_LETTER_DISABLED else drive_letter,
                error_callback=self.on_server_error,
                logger=self.logger,
            )
            self.server_thread.start()

            self.frame.after(100, self.check_server_started)

        except Exception as e:
            self.logger.error(f"Fehler beim Starten: {e}", exc_info=True)
            self.log(f"✗ Fehler: {e}", "ERROR")
            self.is_running = False
            self.status_label.config(text="● Gestoppt", foreground="red")
            self.start_button.config(text="Starten", state="normal")
            messagebox.showerror("Fehler", f"Server konnte nicht gestartet werden:\n{e}")

    def check_server_started(self):
        """Prüft ob Server erfolgreich gestartet wurde"""
        if not self.server_thread:
            return

        if self.server_thread.started:
            self.status_label.config(text="● Läuft", foreground="green")
            self.start_button.config(state="normal")

            webdav_url = f"http://localhost:{self.webdav_port_var.get()}"
            self.log(f"✓ Server gestartet: {webdav_url}")

            sftp_config = self.server_thread.config
            self.log(f"  Backend: {sftp_config.user}@{sftp_config.host}:{sftp_config.remote_path}")

        elif self.server_thread.is_alive():
            self.frame.after(100, self.check_server_started)
        else:
            if self.is_running:
                self.on_server_error("Server konnte nicht gestartet werden")

    def on_server_error(self, error_msg):
        """Callback bei Server-Fehler"""

        def show_error():
            self.is_running = False
            self.status_label.config(text="● Fehler", foreground="red")
            self.start_button.config(text="Starten", state="normal")
            self.log(f"✗ Server-Fehler: {error_msg}", "ERROR")
            messagebox.showerror(
                "Server-Fehler", f"Server ({self.tab_title()}) konnte nicht gestartet werden:\n\n{error_msg}"
            )

        self.frame.after(0, show_error)

    def stop_server(self):
        """Stoppt den WebDAV-Server für diese Verbindung"""
        if self.server_thread:
            self.log("⏸ Stoppe Server...")
            self.server_thread.stop()
            self.server_thread = None

        self.is_running = False
        self.status_label.config(text="● Gestoppt", foreground="red")
        self.start_button.config(text="Starten")
        self.log("✓ Server gestoppt")

    def log(self, message, level="INFO"):
        if level == "ERROR":
            self.logger.error(message)
        else:
            self.logger.info(message)


class ThaDAVScpApp:
    """Hauptfenster der Anwendung - verwaltet mehrere ConnectionTabs"""

    def __init__(self, root):
        self.root = root
        self.root.title("ThaDAVSFTP - WebDAV SFTP Bridge")
        self.root.geometry("700x600")

        self.config = ConfigManager(app_name="ThaDAVSFTP", filename="ThaDAVSFTP.config")
        self.tabs = []

        self._create_widgets()
        self._load_connections()

        self.root.after(500, self.auto_start_all)

    def _create_widgets(self):
        toolbar = ttk.Frame(self.root, padding=(10, 5))
        toolbar.pack(fill="x")

        ttk.Button(toolbar, text="+ Neue Verbindung", command=lambda: self.add_tab()).pack(side="left", padx=(0, 5))
        ttk.Button(toolbar, text="Verbindung entfernen", command=self.remove_current_tab).pack(side="left")
        ttk.Button(toolbar, text="Alle Konfigurationen speichern", command=self.save_all).pack(side="right")

        self.notebook = ttk.Notebook(self.root)
        self.notebook.pack(fill="both", expand=True, padx=10, pady=(0, 10))

    # ------------------------------------------------------------------------
    # Verbindungen laden/speichern
    # ------------------------------------------------------------------------

    def _load_connections(self):
        connections = self.config.get("connections")

        if not connections:
            # Migration von der alten Einzel-Verbindungs-Konfiguration
            legacy_host = self.config.get("host")
            if legacy_host:
                connections = [{
                    "ssh_config_file": self.config.get("ssh_config_file", "~/.ssh/config"),
                    "host": legacy_host,
                    "remote_path": self.config.get("remote_path", "/tmp"),
                    "pool_size": self.config.get("pool_size", 3),
                    "webdav_port": self.config.get("webdav_port", 8080),
                    "drive_letter": self.config.get("drive_letter", ""),
                    "autostart": self.config.get("autostart", False),
                }]
                logger.info("Alte Einzel-Verbindungs-Konfiguration in Tab übernommen")
            else:
                connections = [DEFAULT_CONNECTION.copy()]

        for conn_dict in connections:
            self.add_tab(conn_dict)

    def add_tab(self, config_dict=None):
        if config_dict is None:
            config_dict = DEFAULT_CONNECTION.copy()
            config_dict["webdav_port"] = 8080 + len(self.tabs)

        tab = ConnectionTab(self.notebook, config_dict)
        self.tabs.append(tab)
        self.notebook.select(tab.frame)
        return tab

    def remove_current_tab(self):
        current = self._current_tab()
        if current is None:
            return

        if current.is_running:
            if not messagebox.askokcancel(
                "Verbindung entfernen",
                f"'{current.tab_title()}' läuft noch. Server stoppen und Verbindung entfernen?"
            ):
                return
            current.stop_server()

        current.remove_log_handler()
        self.notebook.forget(current.frame)
        self.tabs.remove(current)

    def _current_tab(self):
        try:
            selected = self.notebook.select()
        except tk.TclError:
            return None
        for tab in self.tabs:
            if str(tab.frame) == selected:
                return tab
        return None

    def save_all(self):
        self.config.set("connections", [tab.to_dict() for tab in self.tabs])
        self.config.save()
        messagebox.showinfo("Erfolg", "Alle Konfigurationen wurden gespeichert!")

    # ------------------------------------------------------------------------
    # Autostart
    # ------------------------------------------------------------------------

    def auto_start_all(self):
        autostart_tabs = [tab for tab in self.tabs if tab.autostart_var.get()]
        if not autostart_tabs:
            return

        self.root.iconify()
        for tab in autostart_tabs:
            tab.log("⚡ Autostart aktiviert")
            tab.start_server()

    # ------------------------------------------------------------------------
    # Beenden
    # ------------------------------------------------------------------------

    def on_closing(self):
        running = [tab for tab in self.tabs if tab.is_running]
        if running:
            names = ", ".join(tab.tab_title() for tab in running)
            if not messagebox.askokcancel("Beenden", f"Server laufen noch ({names}). Wirklich beenden?"):
                return
            for tab in running:
                tab.stop_server()

        for tab in self.tabs:
            tab.remove_log_handler()

        self.root.destroy()


def main():
    root = tk.Tk()
    app = ThaDAVScpApp(root)
    root.protocol("WM_DELETE_WINDOW", app.on_closing)
    root.mainloop()


if __name__ == "__main__":
    main()
