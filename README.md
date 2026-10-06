# Logos Maps

For this prepared Mac checkout, see [local testing](docs/LOCAL_TESTING.md) for the fixture demo, QML preview and Basecamp installation. The SDK and app have published macOS/Linux packages in [the separate catalog](https://github.com/anudit/logos-maps-catalog/releases); Basecamp 0.3.1 has loaded both modules. Runtime asset and UI improvements are being released as 0.1.2. Public-testnet deployment and required adoption remain incomplete.

Distribute verified OpenStreetMap PBF snapshots through Logos Storage and a SPEL registry on the Logos Execution Zone. The CLI and Basecamp distribution app share one SDK; consumers can load the standalone SDK without the distribution app.

**This is an implementation in progress, not a prize-complete submission.** Local SDK, registry, native Storage and real standalone-sequencer validation are recorded in [evidence](evidence/). Public testnet deployment, verified coverage and independent ecosystem adoption are tracked honestly in [the self-assessment](docs/SELF_ASSESSMENT.md). No local fixtures count toward adoption.

## Install the CLI

Requires Python 3.9+, Rust 1.94+ for the registry, [SPEL](https://github.com/logos-co/spel), the [LEZ v0.2.4 wallet](https://docs.logos.co/lez/get-started/run-lez-wallet-via-cli), and a native Logos Storage library. No Python runtime dependencies or hosted backend are required.

```sh
python3 -m venv .venv
.venv/bin/pip install -e .
cp config.example.json config.local.json
.venv/bin/logos-maps regions
```

Fill `config.local.json` with your sequencer URL, deployed program ID, registry PDA, signing account, wallet directory and Storage library. Use absolute paths for the Basecamp app. On Apple Silicon with Basecamp installed, the example library is `/Applications/LogosBasecamp.app/Contents/modules/storage_module/libstorage.dylib`. On Linux x86_64, use the `libstorage.so` shipped by `storage_module`, or build [logos-storage-module](https://github.com/logos-co/logos-storage-module). The SDK uses its versioned native C API and streams files on disk.

`wallet_home` points to the wallet that owns `signer`. Only writes need a wallet. Read-only registry discovery and hosted downloads do not need wallet keys or Geofabrik. `geofabrik: false` explicitly disables all canonical HTTP requests; discovery and hosted downloads remain operational.

## Wallet and testnet

The session's local wallet lives in `.wallet/storage.json`; `wallet.local.json` contains its exported storage and recovery phrase, and `.env` contains path references and the public signer address. All three are ignored by Git and the private files have mode `0600`. Never upload them. The upstream CLI currently stores wallet material unencrypted, so a password prompt does not imply encrypted storage.

```sh
set -a
source .env
set +a
.tools/bin/wallet check-health
.tools/bin/wallet auth-transfer init --account-id "Public/$LOGOS_MAPS_SIGNER"
.tools/bin/wallet pinata claim --to "Public/$LOGOS_MAPS_SIGNER"
```

On 2026-10-06, `https://testnet.lez.logos.co` returned a program list missing `authenticated_transfer` and `pinata`; the documented v0.2.4 wallet refused its health check. The new public wallet's observed balance was zero. See [the captured public response](evidence/testnet-programs.json) and [wallet balance](evidence/wallet-balance.json). Funding and deployment must wait for a compatible official sequencer; the local standalone wallet is separate and does not establish public-testnet funding.

## Build and deploy the registry

The program is pinned to SPEL commit `415b7bc` and LEZ `v0.2.4`, the release named by the current official wallet guide. Its program ID changes whenever guest code or build dependencies change.

```sh
rzup install rust 1.97.0
rzup install cargo-risczero 3.0.5
make registry
make idl
```

Find the R0BF-wrapped binary under `registry/methods/target/riscv-guest/` (named `osm_registry.bin`). The native guest build avoids Docker and uses `risc0-build` with the installed guest Rust compiler. Deploy only after `wallet check-health` succeeds:

```sh
wallet deploy-program /absolute/path/to/osm_registry.bin
spel program-id /absolute/path/to/osm_registry.bin --format hex
spel --idl registry/idl.json --program <PROGRAM_ID> pda state
spel --idl registry/idl.json --program <PROGRAM_ID> -- initialize --authority <SIGNER>
```

Save the printed program ID and PDA in your client configuration. **There is currently no deployed public-testnet program ID.** [standalone.json](evidence/standalone.json) records the tested local deployment. Registry initialization binds the signing curator; mutations require that curator's signature. Reads are public. See the [trust model and limits](docs/ARCHITECTURE.md) before running a shared registry.

## Use the CLI

```sh
logos-maps --config config.local.json discover
logos-maps --config config.local.json discover --central
logos-maps --config config.local.json host germany
logos-maps --config config.local.json bulk-host germany france us/california --exclude france
logos-maps --config config.local.json query --region germany
logos-maps --config config.local.json query --parent us
logos-maps --config config.local.json query --cid <CID>
logos-maps --config config.local.json resolve germany
logos-maps --config config.local.json updates
logos-maps --config config.local.json download germany /absolute/path/germany.osm.pbf
logos-maps --config config.local.json import germany /absolute/path/local.osm.pbf
logos-maps --config config.local.json batch-register verified-entries.json
logos-maps --config config.local.json serve
```

Host fetches the snapshot, compares its MD5 with Geofabrik, checks that its version stayed stable, uploads to native Storage with retries, and registers its CID. Local import copies the PBF into a private staging directory before hashing and uploading. Manual batch registration retrieves each CID and rechecks canonical metadata and hashes before submitting. Bulk hosting uploads every selected extract, then submits **one atomic batch transaction**; a failure before submission leaves uploaded data available for recovery, but registers none of the batch.

Hosted downloads fetch by CID through Storage, verify the reconstructed SHA256 and size against the registry, and commit the output atomically. They never contact Geofabrik, and they do not silently switch to Geofabrik on a hosted transfer failure. Unhosted regions use a verified direct fallback. Existing destination files are preserved.

Keep `serve` running after CLI hosting to advertise and serve your mirrored files. The Basecamp SDK keeps its Storage node alive between operations while the module is loaded. Closing a CLI host command alone does not leave a node running.

## Load the Basecamp app

Builds use the official [logos-module-builder](https://github.com/logos-co/logos-module-builder): `mkLogosModule` for the SDK and its QML builder `mkLogosQmlModule` for the GUI and standalone consumer.

```sh
python3 scripts/package_sdk.py
nix build path:./modules/osm_registry#lgx
nix build path:./modules/osm_distribution#lgx
nix build path:./examples/consumer#lgx
```

In Basecamp, use **Settings → Package Manager → Install from file** to install the SDK and distribution `.lgx` files. The Storage dependency must also be installed. Open **Logos Maps**, enter the absolute configuration JSON path and click **Connect**. Select any subset of the 72 regions; deselect individual rows to opt out. **Registry** reads hosted status; **Geofabrik versions** shows canonical versions and unavailable extracts; **Check updates** compares per-region snapshots. **Host selected** verifies, uploads and batch-registers. Select exactly one region and enter a file path to **Download** or **Verify & import**. Details show the CID, parent, level, version and verification metadata.

The separate **OSM SDK Consumer Example** depends only on `osm_registry` and resolves a region to metadata without `osm_distribution`. See [the stable API and worked embedding example](docs/SDK.md). Nix package builds and catalog publishing are being validated; [release setup](docs/RELEASING.md) lists their current state.

## Regions

The frozen set is [regions.json](src/logos_maps/regions.json): **48 country entries + 24 subregions = 72**, with 8 US states, 6 India zones, 6 China provinces and 4 Russia districts. Country keys include `germany`, `great-britain`, `japan`; decomposed keys include `us/california` and `india/southern-zone`. Each key maps to one canonical Geofabrik extract path. `us`, `india`, `china` and `russia` themselves are excluded. `scripts/check_partition.py` checks JSON/Rust parity and non-overlap.

The 2026-10-06 Geofabrik index does not expose standalone `ireland` or `malaysia` extracts. They stay in the frozen list and are shown as unavailable. Combined extracts are not substituted because that would change the predefined geography.

## Validation and evidence

```sh
make test
python3 scripts/check_partition.py
LOGOS_STORAGE_LIBRARY=/absolute/path/libstorage.so PYTHONPATH=src \
  python3 -m unittest discover -s tests -p test_native_storage.py -v
python3 scripts/integration.py --lez-source /path/to/lez-v0.2.4 \
  --storage-library /absolute/path/libstorage.so --spel /absolute/path/spel \
  --wallet /absolute/path/wallet --r0vm /absolute/path/r0vm
```

The integration runner starts a **real standalone sequencer**, creates an isolated wallet, initializes and funds it locally, deploys the actual registry binary, and runs host → store → register → query → download plus batch-registration checks. Canonical HTTP is a deterministic fixture and `RISC0_DEV_MODE=1` is used for standalone proofs. Native Storage and guest execution are real; fixture bytes and local entries are explicitly excluded from adoption coverage. CI includes this runner on Linux and macOS alongside package builds.

[Cycle-count measurement](docs/PERFORMANCE.md) covers register and batch-register. To produce public coverage evidence after deployment, run `python3 scripts/coverage.py --config config.local.json`. Independent SDK consumer repositories must be listed in `evidence/adoption.json`; the example in this repository is not an independent adopter.

## Licenses

Code is dual licensed under [MIT](LICENSE-MIT) or [Apache-2.0](LICENSE-APACHE-v2). OSM data is separately licensed under the [Open Database License](https://www.openstreetmap.org/copyright), with attribution to OpenStreetMap contributors. Snapshots are distributed from Geofabrik; this project does not render maps or provide routing, geocoding, tiles or live OSM synchronization. No analytics are collected.
