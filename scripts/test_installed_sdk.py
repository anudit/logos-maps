#!/usr/bin/env python3
"""Exercise a packaged Basecamp SDK through its actual generated module C ABI."""
import argparse
import ctypes
import hashlib
import json
import os
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--module", type=Path, default=ROOT / ".maps/basecamp-test/modules/osm_registry/osm_registry_plugin.dylib")
    parser.add_argument("--config", type=Path, default=ROOT / ".maps/demo-config.json")
    args = parser.parse_args()
    os.environ.setdefault("LOGOS_MAPS_PYTHON", sys.executable)
    native = ctypes.CDLL(str(args.module.resolve()))
    native.logos_module_dispatch.argtypes = [ctypes.c_char_p, ctypes.c_char_p]
    native.logos_module_dispatch.restype = ctypes.c_void_p
    native.logos_module_string_free.argtypes = [ctypes.c_void_p]
    native.logos_module_about_to_unload.restype = ctypes.c_int

    def call(method, parameters):
        pointer = native.logos_module_dispatch(method.encode(), json.dumps(parameters).encode())
        if not pointer:
            raise RuntimeError("Null module response: " + method)
        try:
            value = json.loads(ctypes.string_at(pointer).decode())
            if isinstance(value, str):
                value = json.loads(value)
            if isinstance(value, dict) and "error" in value:
                raise RuntimeError(value["error"])
            return value
        finally:
            native.logos_module_string_free(pointer)

    def request(payload):
        job = call("request", [json.dumps(payload)])["id"]
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            for event in call("poll", [str(job)]):
                if "success" in event:
                    if not event["success"]:
                        raise RuntimeError(event["error"])
                    return event["result"]
            time.sleep(0.05)
        raise RuntimeError("SDK job timed out")

    try:
        assert call("configure", [str(args.config.resolve())])["success"]
        assert len(request({"action": "regions"})) == 72
        regions = request({"action": "discover", "central": False})
        assert sum(bool(region.get("hosted")) for region in regions) == 3
        entry = request({"action": "resolve", "region": "germany"})
        assert request({"action": "query", "cid": entry["cid"]})[0]["region"] == "germany"
        with tempfile.TemporaryDirectory(prefix="maps-sdk-") as directory:
            destination = Path(directory) / "germany.osm.pbf"
            result = request({"action": "download", "region": "germany", "destination": str(destination)})
            assert result["verified"]
            assert hashlib.sha256(destination.read_bytes()).hexdigest() == entry["sha256"]
        evidence = {"module": "osm_registry", "interface": "generated module C ABI",
                    "fixture_bytes": True, "packaged_engine_override": "LOGOS_MAPS_ARCHIVE" in os.environ,
                    "regions": 72, "hosted_fixtures": 3, "discover_resolve_query_download": "passed"}
        (ROOT / "evidence/installed-sdk.json").write_text(json.dumps(evidence, indent=2) + "\n")
        print("Installed SDK C ABI: discovery, resolve, CID query and verified download passed")
    finally:
        native.logos_module_about_to_unload()


if __name__ == "__main__":
    main()
