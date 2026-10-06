# Try the app locally

The SDK, Rust guest and native Storage pipeline have passed the real standalone test on this Mac. The QML preview also passes against that node. Installing the app inside Basecamp still requires building its portable packages; this has not yet been verified. Public testnet funding and deployment remain blocked by the incompatible official endpoint, independently of local testing.

## Immediate local preview

The session installed the required local tools under ignored `.tools/` and Qt bindings under `.venv/`. These commands are for this prepared checkout. The demo creates a separate wallet, funds it on its local node, deploys the registry and hosts three small fixtures through the installed Storage library. It prints `Local demo ready` when provisioning finishes. Keep this terminal open; Ctrl-C stops its node. Each run creates an isolated demo directory.

```sh
cd /Users/anudit/Documents/GitHub/logos-maps
PYTHONPATH=src /opt/homebrew/bin/python3.12 scripts/local_demo.py
```

If the demo is already running on port 33341, use it rather than starting another. In a second terminal:

```sh
cd /Users/anudit/Documents/GitHub/logos-maps
.venv/bin/python scripts/preview.py
```

This opens the distribution app's actual `Main.qml` and packaged SDK worker. It automatically connects to `.maps/demo-config.json`. It is a desktop preview; it does not install a plugin into Basecamp. Germany, France and California are hosted test fixtures, **not usable OSM maps** and not adoption evidence. Geofabrik is disabled in the demo configuration, so hosting/import/update actions will report that canonical access is disabled.

Select Germany, enter a new absolute destination such as `/tmp/logos-maps-germany.osm.pbf`, and click Download. The tiny fixture is fetched by CID from native Storage and checked against its recorded SHA256 and size. Existing destination files are protected. Inspect Details to see the registry metadata, or test the same SDK from the CLI:

```sh
PYTHONPATH=src python3 -m logos_maps.cli --config .maps/demo-config.json resolve germany
PYTHONPATH=src python3 -m logos_maps.cli --config .maps/demo-config.json download germany /tmp/logos-maps-germany.osm.pbf
```

For a fresh checkout, follow the tool-building steps in the README and `scripts/integration.py`; `.tools/` binaries and demo wallets are intentionally not distributed. The optional preview needs Python 3.10+ and PySide6 (`python -m pip install PySide6` in a virtual environment).

## Install in the installed Logos Basecamp

Your installed `/Applications/LogosBasecamp.app` is version 0.3.1. Its portable bundle needs portable `.lgx` packages, rather than packages referring to a builder's `/nix/store`. Nix is not installed on this Mac; the following are build instructions, not claims that package outputs already exist.

With Nix and flakes available, from this repository:

```sh
python3 scripts/package_sdk.py
nix build path:./modules/osm_registry#lgx-portable --out-link result-sdk-portable
nix build path:./modules/osm_distribution#lgx-portable --out-link result-app-portable
```

Open Basecamp's package manager and install the SDK `.lgx` from `result-sdk-portable`, then the distribution `.lgx` from `result-app-portable` using its local package installation control. Retain the installed `storage_module` dependency. Once a catalog release is published, add its `logos-repo.json` URL to Settings → Package Repositories and install **OSM Distribution** from the catalog instead. The catalog URLs and workflow are in [RELEASING.md](RELEASING.md).

Launch OSM Distribution, enter the absolute configuration path `/Users/anudit/Documents/GitHub/logos-maps/.maps/demo-config.json`, and click Connect. Keep the local demo node running. The SDK worker needs Python 3.9+; for this checkout launch Basecamp with the installed interpreter selected explicitly if necessary:

```sh
LOGOS_MAPS_PYTHON=/opt/homebrew/bin/python3.12 /Applications/LogosBasecamp.app/Contents/MacOS/LogosBasecamp
```

Quit an existing Basecamp instance first so the new process receives that environment. Check its session logs if a package fails to load; platform/protocol compatibility must be verified by the first actual package installation. Once loaded, repeat the Germany download above and confirm the UI reports integrity verified.

For real Geofabrik hosting, use a compatible deployed registry and a funded authorized wallet in a separate configuration with `geofabrik: true`. The demo registry contains fixture versions; use a fresh registry for real data rather than mixing those with canonical snapshots.
