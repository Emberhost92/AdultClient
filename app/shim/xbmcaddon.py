import json
import os

_ADDON_PATH = os.environ.get("AH_ADDON", "")
_PROFILE = os.environ.get("AH_PROFILE", "")
_SETTINGS_PATH = os.path.join(_PROFILE, "settings.json") if _PROFILE else ""
_settings = None


def _load():
    global _settings
    if _settings is None:
        _settings = {}
        if _SETTINGS_PATH and os.path.exists(_SETTINGS_PATH):
            try:
                with open(_SETTINGS_PATH, "r", encoding="utf-8") as handle:
                    _settings = json.load(handle)
            except Exception:
                _settings = {}
    return _settings


def _save():
    if not _SETTINGS_PATH:
        return
    os.makedirs(os.path.dirname(_SETTINGS_PATH), exist_ok=True)
    with open(_SETTINGS_PATH, "w", encoding="utf-8") as handle:
        json.dump(_load(), handle, ensure_ascii=False, indent=2)


class Addon:
    def __init__(self, id=None):
        self.id = id or "plugin.video.adulthideout"

    def getAddonInfo(self, key):
        key = (key or "").lower()
        if key == "id":
            return self.id
        if key == "path":
            return _ADDON_PATH
        if key in ("profile", "profilepath"):
            return _PROFILE
        if key == "name":
            return "Adult Client"
        if key in ("author", "provider-name"):
            return "emberhost"
        if key == "version":
            return "1.0.24"
        if key == "icon":
            return os.path.join(_ADDON_PATH, "resources", "logos", "icon.png")
        if key == "fanart":
            return os.path.join(_ADDON_PATH, "resources", "logos", "fanart.jpg")
        return ""

    def getSetting(self, key):
        return str(_load().get(key, ""))

    def setSetting(self, key, value):
        _load()[str(key)] = "" if value is None else str(value)
        _save()

    def getSettingBool(self, key):
        return self.getSetting(key).lower() == "true"

    def getSettingInt(self, key):
        try:
            return int(self.getSetting(key) or "0")
        except ValueError:
            return 0

    def getLocalizedString(self, id):
        return ""

    def openSettings(self):
        return None
