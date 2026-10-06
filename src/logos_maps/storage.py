"""Versioned libstorage C API, also used by Basecamp's Storage module.

Files never pass through JSON or base64. Keep this node running to mirror data.
"""
import ctypes as C
import json
import threading
from pathlib import Path

from .models import MapsError


class StorageError(MapsError):
    pass


class NativeStorage:
    CALLBACK = C.CFUNCTYPE(None, C.c_int, C.c_void_p, C.c_size_t, C.c_void_p)

    def __init__(self, library, config, timeout=1800, progress=None):
        if not library:
            raise MapsError("Configure storage_library with the path to libstorage")
        self.lib = C.CDLL(str(Path(library).expanduser().resolve()))
        self.timeout, self.progress = timeout, progress
        self.pending = []  # callbacks must outlive native calls, even on timeout
        self.context = None
        self.lib.storage_new.argtypes = [C.c_char_p, self.CALLBACK, C.c_void_p]
        self.lib.storage_new.restype = C.c_void_p
        types = {
            "start": [], "stop": [], "close": [],
            "upload_init": [C.c_char_p, C.c_size_t, C.c_bool],
            "upload_file": [C.c_char_p], "upload_cancel": [C.c_char_p],
            "download_init": [C.c_char_p, C.c_size_t, C.c_bool, C.c_bool, C.c_bool],
            "download_stream": [C.c_char_p, C.c_size_t, C.c_char_p],
        }
        for name, args in types.items():
            fn = getattr(self.lib, "storage_" + name)
            fn.argtypes = [C.c_void_p] + args + [self.CALLBACK, C.c_void_p]
            fn.restype = C.c_int
        self.lib.storage_destroy.argtypes = [C.c_void_p]
        self.lib.storage_destroy.restype = C.c_int
        callback, done, result = self._callback()
        self.context = self.lib.storage_new(json.dumps(config).encode(), callback, None)
        self._finish(done, result, "initialize")
        if not self.context:
            raise StorageError("Storage initialization returned no context")
        self._call("start")

    def _callback(self):
        done = threading.Event()
        result = []

        @self.CALLBACK
        def callback(code, pointer, length, _):
            msg = C.string_at(pointer, length).decode("utf-8", "replace") if pointer else ""
            if code == 3:
                if self.progress:
                    self.progress(msg)
                return
            result.append((code, msg))
            done.set()

        self.pending.append(callback)
        return callback, done, result

    def _finish(self, done, result, operation):
        if not done.wait(self.timeout):
            raise StorageError("Storage %s timed out after %ss" % (operation, self.timeout))
        code, msg = result[0]
        if code != 0:
            raise StorageError("Storage %s failed: %s" % (operation, msg))
        return msg

    def _call(self, operation, *args):
        callback, done, result = self._callback()
        status = getattr(self.lib, "storage_" + operation)(self.context, *args, callback, None)
        if status != 0 and not done.is_set():
            raise StorageError("Storage %s rejected the request (%s)" % (operation, status))
        return self._finish(done, result, operation)

    def upload(self, file):
        session = self._call("upload_init", str(Path(file).resolve()).encode(), 65536, True)
        try:
            return self._call("upload_file", session.encode())
        except StorageError:
            try:
                self._call("upload_cancel", session.encode())
            except StorageError:
                pass
            raise

    def download(self, cid, file):
        self._call("download_init", cid.encode(), 65536, False, False, True)
        self._call("download_stream", cid.encode(), 65536, str(Path(file).resolve()).encode())

    def close(self):
        if self.context:
            self._call("stop")
            self._call("close")
            if self.lib.storage_destroy(self.context) != 0:
                raise StorageError("Storage destroy failed")
            self.context = None

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()
