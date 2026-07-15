from config_manager import ConfigManager


def test_save_and_load_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))  # falls je unter Windows getestet

    cm = ConfigManager(app_name="TestApp", filename="test.config")
    cm.set("foo", "bar")
    cm.save()

    cm2 = ConfigManager(app_name="TestApp", filename="test.config")
    assert cm2.get("foo") == "bar"


def test_get_returns_default_when_missing(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))

    cm = ConfigManager(app_name="TestApp", filename="test.config")
    assert cm.get("missing", "default_value") == "default_value"
