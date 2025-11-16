import json
import os
import logging

logger = logging.getLogger(__name__)

class ConfigManager:
    def __init__(self, app_name="ThaDAVSFTP", filename="ThaDAVSFTP.config"):
        self.config_path = self._get_config_path(app_name)
        self.config_file = os.path.join(self.config_path, filename)
        self.data = {}
        self._ensure_directory_exists()
        self.load()

    @staticmethod
    def _get_config_path(app_name):
        home_dir = os.path.expanduser("~")
        if os.name == "nt":
            return os.path.join(home_dir, "AppData", "Local", app_name)
        return os.path.join(home_dir, ".config", app_name)

    def _ensure_directory_exists(self):
        if not os.path.exists(self.config_path):
            os.makedirs(self.config_path)

    def load(self):
        try:
            with open(self.config_file, "r", encoding="utf-8") as f:
                self.data = json.load(f)
        except (IOError, json.JSONDecodeError):
            logger.warning("Config file not found or invalid. Starting with empty config.")
            self.data = {}

    def save(self):
        try:
            with open(self.config_file, "w", encoding="utf-8") as f:
                json.dump(self.data, f, indent=4)
        except IOError as e:
            logger.error(f"Could not save config file: {e}")

    def get(self, key, default=None):
        return self.data.get(key, default)

    def set(self, key, value):
        self.data[key] = value
