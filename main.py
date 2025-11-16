import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import logging
import threading
import sys
from pathlib import Path
from os.path import expanduser

from config_manager import ConfigManager
from webdav_sftp import SFTPConfig, SFTPProvider
from wsgidav.wsgidav_app import WsgiDAVApp
from cheroot import wsgi
import ssh_helper

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class WebDAVServerThread(threading.Thread):
    """Thread für WebDAV-Server"""

    def __init__(self, config, webdav_port, error_callback=None):
        super().__init__(daemon=True)
        self.config = config
        self.webdav_port = webdav_port
        self.server = None
        self.provider = None
        self._stop_event = threading.Event()
        self.error_callback = error_callback
        self.started = False

    def run(self):
        try:
            # Erstelle Provider (kann SSH-Fehler werfen)
            logger.info("Erstelle SFTP-Verbindungen...")
            self.provider = SFTPProvider(self.config)

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

            self.started = True
            logger.info(f"WebDAV Server gestartet auf Port {self.webdav_port}")
            self.server.start()

        except Exception as e:
            logger.error(f"Fehler beim Starten des Servers: {e}")
            if self.error_callback:
                self.error_callback(str(e))

    def stop(self):
        """Stoppt den Server"""
        if self.server:
            logger.info("Stoppe WebDAV Server...")
            self.server.stop()
        if self.provider:
            self.provider.pool.close()
        self._stop_event.set()


class ThaDAVScpGUI:
    """Hauptfenster der Anwendung"""

    def __init__(self, root):
        self.root = root
        self.root.title("ThaDAVSFTP - WebDAV SFTP Bridge")
        self.root.geometry("600x500")

        # Config Manager
        self.config = ConfigManager(app_name="ThaDAVSFTP", filename="ThaDAVSFTP.config")

        # Server Thread
        self.server_thread = None
        self.is_running = False

        # Minimiert-Flag
        self.start_minimized = False

        # GUI aufbauen
        self.create_widgets()

        # Lade gespeicherte Konfiguration
        self.load_config()

        # Prüfe Autostart
        if self.autostart_var.get():
            self.start_minimized = True
            self.root.after(500, self.auto_start)

    def create_widgets(self):
        """Erstellt alle GUI-Elemente"""

        # === Status-Frame ===
        status_frame = ttk.LabelFrame(self.root, text="Server Status", padding=10)
        status_frame.pack(fill="x", padx=10, pady=5)

        self.status_label = ttk.Label(
            status_frame,
            text="● Gestoppt",
            font=("Arial", 12, "bold"),
            foreground="red"
        )
        self.status_label.pack(side="left", padx=5)

        self.start_button = ttk.Button(
            status_frame,
            text="Starten",
            command=self.toggle_server,
            width=15
        )
        self.start_button.pack(side="right", padx=5)

        # === SSH Config Frame ===
        ssh_frame = ttk.LabelFrame(self.root, text="SSH Konfiguration", padding=10)
        ssh_frame.pack(fill="x", padx=10, pady=5)

        # SSH Config Datei
        ttk.Label(ssh_frame, text="SSH Config Datei:").grid(row=0, column=0, sticky="w", pady=2)

        config_row = ttk.Frame(ssh_frame)
        config_row.grid(row=0, column=1, sticky="ew", pady=2)

        self.ssh_config_var = tk.StringVar(value="~/.ssh/config")
        ttk.Entry(config_row, textvariable=self.ssh_config_var).pack(side="left", fill="x", expand=True)
        ttk.Button(config_row, text="...", width=3, command=self.browse_ssh_config).pack(side="right", padx=(5, 0))

        # Host Auswahl
        ttk.Label(ssh_frame, text="Host:").grid(row=1, column=0, sticky="w", pady=2)

        host_row = ttk.Frame(ssh_frame)
        host_row.grid(row=1, column=1, sticky="ew", pady=2)

        self.host_var = tk.StringVar()
        self.host_combo = ttk.Combobox(host_row, textvariable=self.host_var, state="readonly")
        self.host_combo.pack(side="left", fill="x", expand=True)
        ttk.Button(host_row, text="Laden", command=self.load_ssh_hosts).pack(side="right", padx=(5, 0))

        # Remote Path
        ttk.Label(ssh_frame, text="Remote Path:").grid(row=2, column=0, sticky="w", pady=2)
        self.remote_path_var = tk.StringVar(value="/tmp")
        ttk.Entry(ssh_frame, textvariable=self.remote_path_var).grid(row=2, column=1, sticky="ew", pady=2)

        # Pool Size
        ttk.Label(ssh_frame, text="Pool Size:").grid(row=3, column=0, sticky="w", pady=2)
        self.pool_size_var = tk.IntVar(value=3)
        ttk.Spinbox(ssh_frame, from_=1, to=10, textvariable=self.pool_size_var, width=10).grid(row=3, column=1,
                                                                                               sticky="w", pady=2)

        ssh_frame.columnconfigure(1, weight=1)

        # === WebDAV Config Frame ===
        webdav_frame = ttk.LabelFrame(self.root, text="WebDAV Konfiguration", padding=10)
        webdav_frame.pack(fill="x", padx=10, pady=5)

        ttk.Label(webdav_frame, text="Port:").grid(row=0, column=0, sticky="w", pady=2)
        self.webdav_port_var = tk.IntVar(value=8080)
        ttk.Spinbox(webdav_frame, from_=1024, to=65535, textvariable=self.webdav_port_var, width=10).grid(row=0,
                                                                                                          column=1,
                                                                                                          sticky="w",
                                                                                                          pady=2)

        webdav_frame.columnconfigure(1, weight=1)

        # === Einstellungen Frame ===
        settings_frame = ttk.LabelFrame(self.root, text="Einstellungen", padding=10)
        settings_frame.pack(fill="x", padx=10, pady=5)

        self.autostart_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            settings_frame,
            text="Autostart (Server startet automatisch und Fenster minimiert sich)",
            variable=self.autostart_var
        ).pack(anchor="w")

        # === Buttons Frame ===
        button_frame = ttk.Frame(self.root, padding=10)
        button_frame.pack(fill="x", padx=10, pady=5)

        ttk.Button(button_frame, text="Konfiguration speichern", command=self.save_config).pack(side="left", padx=5)
        ttk.Button(button_frame, text="Zurücksetzen", command=self.load_config).pack(side="left", padx=5)

        # === Log Frame ===
        log_frame = ttk.LabelFrame(self.root, text="Log", padding=10)
        log_frame.pack(fill="both", expand=True, padx=10, pady=5)

        self.log_text = tk.Text(log_frame, height=8, state="disabled", wrap="word")
        self.log_text.pack(side="left", fill="both", expand=True)

        scrollbar = ttk.Scrollbar(log_frame, command=self.log_text.yview)
        scrollbar.pack(side="right", fill="y")
        self.log_text.config(yscrollcommand=scrollbar.set)

        # Log Handler
        self.setup_log_handler()

    def setup_log_handler(self):
        """Richtet Log-Handler für Text-Widget ein"""

        class TextHandler(logging.Handler):
            def __init__(self, text_widget):
                super().__init__()
                self.text_widget = text_widget

            def emit(self, record):
                msg = self.format(record)

                def append():
                    self.text_widget.config(state="normal")
                    self.text_widget.insert("end", msg + "\n")
                    self.text_widget.see("end")
                    self.text_widget.config(state="disabled")

                self.text_widget.after(0, append)

        handler = TextHandler(self.log_text)
        handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s', datefmt='%H:%M:%S'))
        logging.getLogger().addHandler(handler)

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
            from sshconf import read_ssh_config

            config = read_ssh_config(ssh_config_path)
            hosts = [h for h in config.hosts() if h != "*"]

            self.host_combo['values'] = hosts
            if hosts and not self.host_var.get():
                self.host_combo.current(0)

            self.log(f"✓ {len(hosts)} Hosts geladen")

        except Exception as e:
            self.log(f"✗ Fehler beim Laden der Hosts: {e}", "ERROR")
            messagebox.showerror("Fehler", f"SSH Config konnte nicht geladen werden:\n{e}")

    def load_config(self):
        """Lädt gespeicherte Konfiguration"""
        self.ssh_config_var.set(self.config.get("ssh_config_file", "~/.ssh/config"))
        self.host_var.set(self.config.get("host", ""))
        self.remote_path_var.set(self.config.get("remote_path", "/tmp"))
        self.pool_size_var.set(self.config.get("pool_size", 3))
        self.webdav_port_var.set(self.config.get("webdav_port", 8080))
        self.autostart_var.set(self.config.get("autostart", False))

        # Lade Hosts wenn Config-Datei existiert
        if self.ssh_config_var.get():
            self.load_ssh_hosts()

        self.log("✓ Konfiguration geladen")

    def save_config(self):
        """Speichert aktuelle Konfiguration"""
        self.config.set("ssh_config_file", self.ssh_config_var.get())
        self.config.set("host", self.host_var.get())
        self.config.set("remote_path", self.remote_path_var.get())
        self.config.set("pool_size", self.pool_size_var.get())
        self.config.set("webdav_port", self.webdav_port_var.get())
        self.config.set("autostart", self.autostart_var.get())
        self.config.save()

        self.log("✓ Konfiguration gespeichert")
        messagebox.showinfo("Erfolg", "Konfiguration wurde gespeichert!")

    def toggle_server(self):
        """Startet oder stoppt den Server"""
        if self.is_running:
            self.stop_server()
        else:
            self.start_server()

    def start_server(self):
        """Startet den WebDAV-Server"""
        try:
            # Validierung
            if not self.host_var.get():
                messagebox.showerror("Fehler", "Bitte Host auswählen!")
                return

            # Erstelle SFTP Config
            sftp_config = SFTPConfig.from_ssh_config(
                host=self.host_var.get(),
                ssh_config_path=expanduser(self.ssh_config_var.get()),
                remote_path=self.remote_path_var.get(),
                pool_size=self.pool_size_var.get()
            )

            # Update UI sofort
            self.is_running = True
            self.status_label.config(text="● Verbinde...", foreground="orange")
            self.start_button.config(text="Stoppen", state="disabled")
            self.log("⏳ Starte Server, baue SSH-Verbindungen auf...")

            # Starte Server Thread mit Error-Callback
            self.server_thread = WebDAVServerThread(
                sftp_config,
                self.webdav_port_var.get(),
                error_callback=self.on_server_error
            )
            self.server_thread.start()

            # Überwache Server-Start
            self.root.after(100, self.check_server_started)

        except Exception as e:
            logger.error(f"Fehler beim Starten: {e}", exc_info=True)
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
            # Server erfolgreich gestartet
            self.status_label.config(text="● Läuft", foreground="green")
            self.start_button.config(state="normal")

            webdav_url = f"http://localhost:{self.webdav_port_var.get()}"
            self.log(f"✓ Server gestartet: {webdav_url}")

            sftp_config = self.server_thread.config
            self.log(f"  Backend: {sftp_config.user}@{sftp_config.host}:{sftp_config.remote_path}")

            # Minimiere Fenster bei Autostart
            if self.start_minimized:
                self.root.iconify()
                self.start_minimized = False

        elif self.server_thread.is_alive():
            # Server noch am Starten
            self.root.after(100, self.check_server_started)
        else:
            # Thread beendet ohne started=True -> Fehler
            if self.is_running:
                self.on_server_error("Server konnte nicht gestartet werden")

    def on_server_error(self, error_msg):
        """Callback bei Server-Fehler"""

        def show_error():
            self.is_running = False
            self.status_label.config(text="● Fehler", foreground="red")
            self.start_button.config(text="Starten", state="normal")
            self.log(f"✗ Server-Fehler: {error_msg}", "ERROR")
            messagebox.showerror("Server-Fehler", f"Server konnte nicht gestartet werden:\n\n{error_msg}")

        # Führe im Main-Thread aus
        self.root.after(0, show_error)

    def stop_server(self):
        """Stoppt den WebDAV-Server"""
        if self.server_thread:
            self.log("⏸ Stoppe Server...")
            self.server_thread.stop()
            self.server_thread = None

        # Update UI
        self.is_running = False
        self.status_label.config(text="● Gestoppt", foreground="red")
        self.start_button.config(text="Starten")
        self.log("✓ Server gestoppt")

    def auto_start(self):
        """Autostart-Funktion"""
        self.log("⚡ Autostart aktiviert")
        self.start_server()

    def log(self, message, level="INFO"):
        """Schreibt Nachricht ins Log"""
        if level == "ERROR":
            logger.error(message)
        else:
            logger.info(message)

    def on_closing(self):
        """Handler für Fenster-Schließen"""
        if self.is_running:
            if messagebox.askokcancel("Beenden", "Server läuft noch. Wirklich beenden?"):
                self.stop_server()
                self.root.destroy()
        else:
            self.root.destroy()


def main():
    root = tk.Tk()
    app = ThaDAVScpGUI(root)
    root.protocol("WM_DELETE_WINDOW", app.on_closing)
    root.mainloop()


if __name__ == "__main__":
    main()
