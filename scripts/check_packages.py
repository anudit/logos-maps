#!/usr/bin/env python3
"""Verify portable LGX runtime contents, including the actual packaged SDK engine."""
import argparse
import io
import json
import tarfile
import zipfile
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("packages", type=Path, nargs="+")
    args = parser.parse_args()
    for path in args.packages:
        with tarfile.open(path, "r:gz") as package:
            files = {name.removeprefix("./") for name in package.getnames()}
            manifest = json.load(package.extractfile("manifest.json"))
            assert any(name.startswith("variants/") for name in files), "No platform variant"
            assert not any("-dev/" in name for name in files), "Expected a portable package"
            if manifest["name"] == "osm_registry":
                engine = "assets/engine/maps_sdk.pyz"
                assert engine in files, "SDK worker archive is missing from package assets"
                with zipfile.ZipFile(io.BytesIO(package.extractfile(engine).read())) as archive:
                    regions = json.loads(archive.read("logos_maps/regions.json"))
                    assert len(regions) == 72
                    assert "logos_maps/cli.py" in archive.namelist()
                assert "assets/engine/idl.json" in files
            if manifest["type"] == "ui_qml":
                assert "assets/icon.png" in files
            print(manifest["name"] + " " + manifest["version"] + ": portable runtime contents passed")


if __name__ == "__main__":
    main()
