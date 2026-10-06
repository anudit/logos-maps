#!/usr/bin/env python3
"""Install built LGX packages with Basecamp's native manager into an isolated profile."""
import argparse
import ctypes
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("packages", type=Path, nargs="+")
    parser.add_argument("--basecamp", type=Path, default=Path("/Applications/LogosBasecamp.app"))
    parser.add_argument("--profile", type=Path, default=ROOT / ".maps/basecamp-test")
    args = parser.parse_args()
    profile = args.profile.resolve()
    profile.mkdir(parents=True, exist_ok=True)
    library = args.basecamp / "Contents/modules/package_manager/libpackage_manager_lib.dylib"
    native = ctypes.CDLL(str(library))
    native.lgpm_create.restype = ctypes.c_void_p
    native.lgpm_free.argtypes = [ctypes.c_void_p]
    native.lgpm_free_string.argtypes = [ctypes.c_void_p]
    native.lgpm_get_last_error.restype = ctypes.c_char_p
    for method in ("lgpm_set_embedded_modules_dir", "lgpm_set_embedded_ui_plugins_dir",
                   "lgpm_set_user_modules_dir", "lgpm_set_user_ui_plugins_dir"):
        getattr(native, method).argtypes = [ctypes.c_void_p, ctypes.c_char_p]
    native.lgpm_install_file.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_bool,
                                       ctypes.c_void_p, ctypes.c_void_p]
    native.lgpm_install_file.restype = ctypes.c_void_p
    native.lgpm_get_installed_modules.argtypes = [ctypes.c_void_p]
    native.lgpm_get_installed_modules.restype = ctypes.c_void_p
    native.lgpm_get_installed_ui_plugins.argtypes = [ctypes.c_void_p]
    native.lgpm_get_installed_ui_plugins.restype = ctypes.c_void_p
    context = native.lgpm_create()
    if not context:
        raise SystemExit("Native package manager could not create a context")

    def string(pointer):
        if not pointer:
            raise RuntimeError((native.lgpm_get_last_error() or b"Package manager failed").decode())
        try:
            return ctypes.string_at(pointer).decode()
        finally:
            native.lgpm_free_string(pointer)

    try:
        native.lgpm_set_embedded_modules_dir(context, str(args.basecamp / "Contents/modules").encode())
        native.lgpm_set_embedded_ui_plugins_dir(context, str(args.basecamp / "Contents/plugins").encode())
        native.lgpm_set_user_modules_dir(context, str(profile / "modules").encode())
        native.lgpm_set_user_ui_plugins_dir(context, str(profile / "plugins").encode())
        for package in args.packages:
            if not package.is_file() or package.suffix != ".lgx":
                raise ValueError("Expected a built .lgx file: " + str(package))
            print("Installed: " + string(native.lgpm_install_file(context, str(package.resolve()).encode(),
                                                                 False, None, None)))
        installed = {"modules": json.loads(string(native.lgpm_get_installed_modules(context))),
                     "apps": json.loads(string(native.lgpm_get_installed_ui_plugins(context)))}
        (profile / "installed.json").write_text(json.dumps(installed, indent=2) + "\n")
        print("Isolated Basecamp profile: " + str(profile))
    finally:
        native.lgpm_free(context)


if __name__ == "__main__":
    main()
