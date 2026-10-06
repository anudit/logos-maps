# Build and catalog publishing

The separate catalog is prepared locally in `.maps/catalog` from the upstream release template. Run `python3 scripts/prepare_catalog.py` after committing source changes to update its `submodules/logos-maps` pointer and both per-module workflows. Its shared release workflow targets Apple Silicon macOS and Linux x86_64 and uses the upstream release action. The template's index rebuild and catalog-validation workflows are retained. Publication and release execution still require explicit approval and successful builds.

The upstream umbrella discovers a module at each submodule root. Because this source repo contains two modules below that root, our umbrella explicitly supplies the two nested module paths to the same shared release workflow. No extra source repositories are needed.

The SDK and GUI are independent Basecamp packages, built from `modules/osm_registry` and `modules/osm_distribution`. Generate the SPEL IDL and `maps_sdk.pyz` before a release; CI rejects generated artifacts that differ from their sources. Both modules have version `0.1.0`. The in-repo consumer is an embedding example and is not counted as ecosystem adoption.

```sh
make idl
python3 scripts/package_sdk.py
nix build path:./modules/osm_registry#lgx
nix build path:./modules/osm_distribution#lgx
```

The core uses `logos-module-builder.lib.mkLogosModule`; QML packages use the builder's supported `mkLogosQmlModule` API. Build on Apple Silicon macOS and x86_64 Linux. The CI workflow builds and uploads `.lgx` artifacts alongside real standalone pipeline evidence. Standard `.lgx` outputs depend on the Nix closure; portable artifacts can be built using each flake's `#lgx-portable` output.

The release catalog should be a fork of [logos-modules-release-base](https://github.com/logos-co/logos-modules-release-base), containing this repository as `submodules/logos-maps`. Its module release workflow calls [logos-modules-release-action](https://github.com/logos-co/logos-modules-release-action) for these two `module_path` values:

* `submodules/logos-maps/modules/osm_registry`
* `submodules/logos-maps/modules/osm_distribution`

Use variants `darwin-arm64,linux-amd64` and the catalog's signing configuration. A separate index workflow calls the action's `rebuild-index.yml@v1` after releases. The catalog's `logos-repo.json` must point `indexUrl` to its rolling `index/index.json` release and declare its signing trust policy. An empty `trustedSigners` means unsigned packages, as in the upstream template.

The intended public URLs are:

* source: `https://github.com/anudit/logos-maps`
* catalog: `https://github.com/anudit/logos-maps-catalog`
* install URL: `https://raw.githubusercontent.com/anudit/logos-maps-catalog/main/logos-repo.json`

These are intended locations until their creation and successful releases are recorded. Do not describe the catalog as installable merely because `logos-repo.json` exists: it needs a published index and both platform assets. The [self-assessment](SELF_ASSESSMENT.md) tracks actual progress.

For Basecamp installation, add the published `logos-repo.json` URL in Settings → Package Repositories, refresh Package Manager, and install `osm_distribution`. Basecamp resolves `osm_registry` and `storage_module` dependencies. To load only the consumer SDK, install `osm_registry` independently.
