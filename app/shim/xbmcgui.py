import os

NOTIFICATION_INFO = 1
NOTIFICATION_WARNING = 2
NOTIFICATION_ERROR = 3

_properties = {}
_notifications = []
_redirects = []
_keyboard_override = {"text": None}


def note_builtin(command):
    text = str(command or "")
    if "Container.Update" in text or "Container.Refresh" in text:
        inner = text
        if "(" in text and ")" in text:
            inner = text[text.find("(") + 1:text.rfind(")")]
        inner = inner.split(",")[0].strip()
        _redirects.append(inner)


def take_keyboard_text(default):
    override = _keyboard_override.get("text")
    if override is not None:
        return override
    return default or ""


def push_notification(title, message):
    _notifications.append({"title": str(title), "message": str(message)})


def drain_ui():
    notes = list(_notifications)
    redirects = list(_redirects)
    _notifications.clear()
    _redirects.clear()
    return notes, redirects


class Window:
    def __init__(self, window_id=0):
        self.window_id = window_id

    def getProperty(self, key):
        return _properties.get((self.window_id, key), "")

    def setProperty(self, key, value):
        _properties[(self.window_id, key)] = "" if value is None else str(value)

    def clearProperty(self, key):
        _properties.pop((self.window_id, key), None)

    def clearProperties(self):
        for prop in list(_properties):
            if prop[0] == self.window_id:
                _properties.pop(prop, None)


class Dialog:
    def notification(self, heading, message, icon=None, time=5000, sound=True):
        push_notification(heading, message)

    def ok(self, heading, message="", line1="", line2="", line3=""):
        push_notification(heading, message or line1)
        return True

    def yesno(self, heading, message="", nolabel="", yeslabel="", autoclose=0, defaultbutton=0):
        push_notification(heading, message)
        return False

    def select(self, heading, list, autoclose=0, preselect=-1, useDetails=False):
        push_notification(heading, "Auswahl im Browser noch nicht umgesetzt.")
        return -1

    def multiselect(self, heading, options, autoclose=0, preselect=None, useDetails=False):
        return []

    def numeric(self, type, heading, default=""):
        return default or ""

    def input(self, heading, default="", type=0, option=0, autoclose=0):
        text = take_keyboard_text(default)
        return text

    def browse(self, type, heading, shares, mask="", useThumbs=False, treatAsFolder=False, default="", enableMultiple=False):
        return default or ""

    def textviewer(self, heading, text, usemono=False):
        push_notification(heading, (text or "")[:240])


class DialogProgress:
    def create(self, heading, message=""):
        return None

    def update(self, percent, message=""):
        return None

    def iscanceled(self):
        return False

    def close(self):
        return None


class DialogProgressBG(DialogProgress):
    pass


class InfoTagVideo:
    def __init__(self, owner):
        self.owner = owner

    def setTitle(self, title):
        self.owner.info.setdefault("video", {})["title"] = title

    def setPlot(self, plot):
        self.owner.info.setdefault("video", {})["plot"] = plot

    def setDuration(self, duration):
        self.owner.info.setdefault("video", {})["duration"] = duration

    def setYear(self, year):
        self.owner.info.setdefault("video", {})["year"] = year

    def setGenres(self, genres):
        self.owner.info.setdefault("video", {})["genre"] = genres

    def setResumePoint(self, *args, **kwargs):
        return None

    def __getattr__(self, name):
        def _setter(*args, **kwargs):
            if args:
                self.owner.info.setdefault("video", {})[name] = args[0]
        return _setter


class ListItem:
    def __init__(self, label="", label2="", path="", offscreen=False):
        self.label = label or ""
        self.label2 = label2 or ""
        self.path = path or ""
        self.art = {}
        self.info = {}
        self.properties = {}
        self.context = []
        self.mimetype = ""
        self.subtitles = []
        self._info_tag = InfoTagVideo(self)

    def setLabel(self, label):
        self.label = label or ""

    def getLabel(self):
        return self.label

    def setLabel2(self, label):
        self.label2 = label or ""

    def setArt(self, art):
        if art:
            self.art.update(art)

    def setInfo(self, type, infoLabels):
        self.info[type] = dict(infoLabels or {})

    def getVideoInfoTag(self):
        return self._info_tag

    def setProperty(self, key, value):
        self.properties[str(key)] = "" if value is None else str(value)

    def getProperty(self, key):
        return self.properties.get(str(key), "")

    def addContextMenuItems(self, items, replaceItems=False):
        self.context = list(items or [])

    def setPath(self, path):
        self.path = path or ""

    def getPath(self):
        return self.path

    def setMimeType(self, mimetype):
        self.mimetype = mimetype or ""

    def setContentLookup(self, enable):
        self.properties["contentlookup"] = "true" if enable else "false"

    def addStreamInfo(self, type, values):
        self.info.setdefault("streams", []).append((type, values))

    def setSubtitles(self, subtitles):
        self.subtitles = list(subtitles or [])

    def setIsFolder(self, is_folder):
        self.properties["isfolder"] = "true" if is_folder else "false"

    def __getattr__(self, name):
        def _noop(*args, **kwargs):
            return None
        return _noop


def __getattr__(name):
    if name.isupper():
        return 0

    class _Fallback:
        def __init__(self, *args, **kwargs):
            pass

        def __getattr__(self, item):
            return lambda *a, **k: None

    return _Fallback
