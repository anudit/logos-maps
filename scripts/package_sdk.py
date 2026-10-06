#!/usr/bin/env python3
"""Build a reproducible stdlib-only Python archive next to the SDK plugin."""
import json
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
output = ROOT / "modules/osm_registry/maps_sdk.pyz"
files = {str(p.relative_to(ROOT / "src")): p.read_bytes()
         for p in sorted((ROOT / "src/logos_maps").iterdir()) if p.suffix in (".py", ".json")}
files["__main__.py"] = b"from logos_maps.cli import main\nmain()\n"
with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
    for name, data in sorted(files.items()):
        info = zipfile.ZipInfo(name, (2026, 1, 1, 0, 0, 0))
        info.compress_type = zipfile.ZIP_DEFLATED
        info.external_attr = 0o644 << 16
        archive.writestr(info, data)
(ROOT / "modules/osm_registry/idl.json").write_bytes((ROOT / "registry/idl.json").read_bytes())
print(output)
