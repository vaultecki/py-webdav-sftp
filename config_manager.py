import json
import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

class ConfigManager:
    def __init__(self, app_name="ThaDAVSFTP", filename="ThaDAVSFTP.config"):
        self.config_path = self._get_config_path(app_name)
        self.config_file = self.config_path / filename
        self.data = {}
        self._ensure_directory_exists()
        self.load()

    @staticmethod
    def _get_config_path(app_name):
        home_dir = Path.home()
        if os.name == "nt":
            return home_dir / "AppData" / "Local" / app_name
        return home_dir / ".config" / app_name

    def _ensure_directory_exists(self):
        if not self.config_path.exists():
            self.config_path.mkdir(parents=True)

    def load(self):
        try:
            with self.config_file.open(encoding="utf-8") as f:
                self.data = json.load(f)
        except (OSError, json.JSONDecodeError):
            logger.warning(
                "Config file not found or invalid. Starting with empty config."
            )
            self.data = {}

    def save(self):
        try:
            with self.config_file.open("w", encoding="utf-8") as f:
                json.dump(self.data, f, indent=4)
        except OSError as e:
            logger.error(f"Could not save config file: {e}")

    def get(self, key, default=None):
        return self.data.get(key, default)

    def set(self, key, value):
        self.data[key] = value
