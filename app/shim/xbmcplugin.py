_state = {
    "items": [],
    "resolved": None,
    "content": "",
    "category": "",
    "succeeded": True,
}

SORT_METHOD_NONE = 0
SORT_METHOD_LABEL = 1
SORT_METHOD_TITLE = 2
SORT_METHOD_DATE = 3
SORT_METHOD_VIDEO_YEAR = 4
SORT_METHOD_UNSORTED = 5
SORT_METHOD_VIDEO_RATING = 6
SORT_METHOD_DURATION = 7


def _reset():
    _state["items"] = []
    _state["resolved"] = None
    _state["content"] = ""
    _state["category"] = ""
    _state["succeeded"] = True


def _snapshot_item(listitem):
    return {
        "label": getattr(listitem, "label", "") or "",
        "label2": getattr(listitem, "label2", "") or "",
        "path": listitem.getPath() if hasattr(listitem, "getPath") else "",
        "art": dict(getattr(listitem, "art", {}) or {}),
        "info": dict(getattr(listitem, "info", {}) or {}),
        "properties": dict(getattr(listitem, "properties", {}) or {}),
        "mimetype": getattr(listitem, "mimetype", "") or "",
        "context": list(getattr(listitem, "context", []) or []),
    }


def addDirectoryItem(handle, url, listitem, isFolder=False, totalItems=0):
    _state["items"].append({
        "url": url or "",
        "isFolder": bool(isFolder),
        "item": _snapshot_item(listitem),
    })
    return True


def addDirectoryItems(handle, items, totalItems=0):
    for url, listitem, is_folder in items:
        addDirectoryItem(handle, url, listitem, is_folder)
    return True


def endOfDirectory(handle, succeeded=True, updateListing=False, cacheToDisc=True):
    _state["succeeded"] = bool(succeeded)


def setResolvedUrl(handle, succeeded, listitem):
    snap = _snapshot_item(listitem)
    _state["resolved"] = {"succeeded": bool(succeeded), "item": snap}
    if succeeded and snap.get("path"):
        import xbmc
        xbmc.Player().play(snap["path"], listitem)


def setContent(handle, content):
    _state["content"] = content or ""


def setPluginCategory(handle, category):
    _state["category"] = category or ""


def setPluginFanart(handle, image=None, color1=None, color2=None, color3=None):
    return None


def addSortMethod(handle, sortMethod, label2Mask=""):
    return None


def setProperty(handle, key, value):
    return None


def __getattr__(name):
    if name.startswith("SORT_"):
        return 0

    def _missing(*args, **kwargs):
        return None

    return _missing
