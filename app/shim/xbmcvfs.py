import os
import shutil

_PROFILE = os.environ.get("AH_PROFILE", "")


def translatePath(path):
    path = path or ""
    if path.startswith("special://profile"):
        rest = path[len("special://profile"):].lstrip("/\\")
        return os.path.join(_PROFILE, rest) if _PROFILE else path
    if path.startswith("special://temp"):
        rest = path[len("special://temp"):].lstrip("/\\")
        base = os.path.join(_PROFILE, "temp") if _PROFILE else os.environ.get("TEMP", ".")
        return os.path.join(base, rest)
    if path.startswith("special://home"):
        rest = path[len("special://home"):].lstrip("/\\")
        base = os.path.dirname(_PROFILE) if _PROFILE else "."
        return os.path.join(base, rest)
    return path


def exists(path):
    return os.path.exists(translatePath(path))


def mkdirs(path):
    os.makedirs(translatePath(path), exist_ok=True)


def mkdir(path):
    mkdirs(path)


def listdir(path):
    real = translatePath(path)
    dirs, files = [], []
    if os.path.isdir(real):
        for name in os.listdir(real):
            if os.path.isdir(os.path.join(real, name)):
                dirs.append(name)
            else:
                files.append(name)
    return dirs, files


def delete(path):
    real = translatePath(path)
    if os.path.isdir(real):
        shutil.rmtree(real, ignore_errors=True)
    elif os.path.exists(real):
        os.remove(real)


def copy(src, dst):
    shutil.copy2(translatePath(src), translatePath(dst))


def rename(src, dst):
    os.replace(translatePath(src), translatePath(dst))


class File:
    def __init__(self, path, mode="r"):
        py_mode = mode.replace("b", "")
        binary = "b" in mode or mode == "w"
        if mode in ("w", "wb", "a", "ab"):
            folder = os.path.dirname(translatePath(path))
            if folder:
                os.makedirs(folder, exist_ok=True)
        flags = mode
        if flags == "w":
            flags = "w"
        self._fh = open(translatePath(path), flags if "b" in flags or flags in ("r", "w", "a") else "r", encoding=None if "b" in (mode + "") else "utf-8")

    def read(self, size=-1):
        return self._fh.read() if size < 0 else self._fh.read(size)

    def write(self, data):
        self._fh.write(data)

    def close(self):
        self._fh.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


def __getattr__(name):
    def _missing(*args, **kwargs):
        return None
    return _missing
