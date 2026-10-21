# Minimal Kodi runtime used by the local web UI.
import time

LOGDEBUG = 0
LOGINFO = 1
LOGWARNING = 2
LOGERROR = 3
LOGFATAL = 4
LOGNONE = 5

PLAYLIST_VIDEO = 1
ISO_639_1 = 0
ISO_639_2 = 1

_windows = {}
_player_state = {
    "playing": False,
    "file": "",
}


def log(msg, level=LOGINFO):
    try:
        print("[xbmc]", msg)
    except Exception:
        pass


def sleep(ms):
    time.sleep(max(0, int(ms)) / 1000.0)


def executebuiltin(command, wait=False):
    from xbmcgui import note_builtin
    note_builtin(command)


def executeJSONRPC(json_string):
    return "{}"


def getCondVisibility(condition):
    return False


def getInfoLabel(label):
    return ""


def getLocalizedString(id):
    return ""


def translatePath(path):
    import xbmcvfs
    return xbmcvfs.translatePath(path)


class Keyboard:
    def __init__(self, default="", heading="", hidden=False):
        import xbmcgui
        self._text = xbmcgui.take_keyboard_text(default or "")
        self._confirmed = bool(self._text)

    def doModal(self, timeout=0):
        return None

    def isConfirmed(self):
        return self._confirmed

    def getText(self):
        return self._text

    def setDefault(self, text):
        self._text = text or ""

    def setHeading(self, heading):
        return None

    def setHiddenInput(self, hidden):
        return None


class Monitor:
    def abortRequested(self):
        return False

    def waitForAbort(self, timeout=0):
        if timeout:
            time.sleep(float(timeout))
        return False


class Player:
    def play(self, item="", listitem=None, windowed=False, startpos=-1):
        path = item
        if hasattr(item, "getPath"):
            path = item.getPath() or getattr(item, "label", "")
        _player_state["playing"] = True
        _player_state["file"] = path or ""

    def stop(self):
        _player_state["playing"] = False
        _player_state["file"] = ""

    def pause(self):
        return None

    def isPlaying(self):
        return bool(_player_state["playing"])

    def isPlayingVideo(self):
        return bool(_player_state["playing"])

    def isPlayingAudio(self):
        return False

    def getPlayingFile(self):
        return _player_state["file"] or ""

    def seekTime(self, seconds):
        return None

    def getTime(self):
        return 0

    def getTotalTime(self):
        return 0


class PlayList:
    def __init__(self, playlist=PLAYLIST_VIDEO):
        self._items = []

    def clear(self):
        self._items = []

    def add(self, url, listitem=None, index=-1):
        self._items.append(url)

    def size(self):
        return len(self._items)

    def getposition(self):
        return 0


def __getattr__(name):
    if name.isupper():
        return 0

    def _missing(*args, **kwargs):
        return None

    return _missing
