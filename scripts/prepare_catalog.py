#!/usr/bin/env python3
"""Prepare the separate release-template catalog locally. Never publish it."""
import argparse
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, default=ROOT / ".maps/catalog")
    parser.add_argument("--template", default="https://github.com/logos-co/logos-modules-release-base.git")
    args = parser.parse_args()
    directory = args.directory.resolve()

    def git(*command):
        subprocess.run(["git", "-C", str(directory), *command], check=True)

    if not (directory / ".git").exists():
        directory.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(["git", "clone", args.template, str(directory)], check=True)
    source = directory / "submodules/logos-maps"
    if not source.exists():
        git("-c", "protocol.file.allow=always", "submodule", "add", str(ROOT), "submodules/logos-maps")
    git("config", "--file", ".gitmodules", "submodule.submodules/logos-maps.url",
        "https://github.com/anudit/logos-maps.git")
    subprocess.run(["git", "-C", str(source), "fetch", "origin"], check=True)
    revision = subprocess.check_output(["git", "-C", str(ROOT), "rev-parse", "HEAD"], text=True).strip()
    subprocess.run(["git", "-C", str(source), "checkout", "--detach", revision], check=True)
    metadata = {"schemaVersion": 1, "name": "logos-maps", "displayName": "Logos Maps",
                "description": "Verified OpenStreetMap distribution and standalone registry SDK.",
                "homepage": "https://github.com/anudit/logos-maps",
                "indexUrl": "https://github.com/anudit/logos-maps-catalog/releases/download/index/index.json",
                "trustedSigners": []}
    (directory / "logos-repo.json").write_text(json.dumps(metadata, indent=2) + "\n")
    (directory / "README.md").write_text('''# Logos Maps catalog

Separate module catalog based on logos-co/logos-modules-release-base.
The source lives in the `submodules/logos-maps` git submodule. The two
module paths are `modules/osm_registry` and `modules/osm_distribution`.
The shared release workflow calls logos-co/logos-modules-release-action
for darwin-arm64 and linux-amd64. Packages are unsigned initially, matching
the empty trustedSigners in logos-repo.json.

After publishing the source revision and this fork, run **Release all map
modules** from Actions. Confirm both platform releases and the rolling
index release succeeded before distributing this installation URL:

https://raw.githubusercontent.com/anudit/logos-maps-catalog/main/logos-repo.json

Add that URL in Basecamp Settings → Package Repositories, refresh the
package manager and install OSM Distribution. The SDK is also independently
installable. Local test instructions are in the source's docs/LOCAL_TESTING.md.

For updates, publish the source commit, update this submodule pointer,
commit it, push, and rerun releases. The umbrella explicitly lists both
nested paths because upstream discovery expects one module per submodule.

This working tree is only a prepared catalog until actual releases succeed.
''')
    workflows = directory / ".github/workflows"
    shared = workflows / "_release-module.yml"
    shared.write_text(shared.read_text().replace("darwin-arm64,linux-amd64,linux-arm64,windows-x86_64",
                                              "darwin-arm64,linux-amd64"))
    template = (workflows / "release-module.yml.template").read_text()
    for module in ("osm_registry", "osm_distribution"):
        content = template.replace("__MODULE__", module).replace(
            "module_path: submodules/" + module, "module_path: submodules/logos-maps/modules/" + module)
        (workflows / ("release-" + module + ".yml")).write_text(content)
    (workflows / "release-all.yml").write_text('''name: Release all map modules
on:
  workflow_dispatch:
    inputs:
      force_build:
        description: Replace assets of an existing version
        type: boolean
        default: false
permissions:
  contents: write
jobs:
  release:
    strategy:
      fail-fast: false
      matrix:
        module_path:
          - submodules/logos-maps/modules/osm_registry
          - submodules/logos-maps/modules/osm_distribution
    uses: ./.github/workflows/_release-module.yml
    with:
      module_path: ${{ matrix.module_path }}
      force_build: ${{ inputs.force_build }}
    secrets: inherit
''')
    git("add", ".gitmodules", "submodules/logos-maps", "logos-repo.json", ".github/workflows", "README.md")
    print("Prepared separate local catalog: " + str(directory))
    print("Source revision: " + revision)
    print("No repository or release has been published.")


if __name__ == "__main__":
    main()
