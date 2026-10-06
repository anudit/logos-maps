# SDK v1 API

`osm_registry` is a standalone Basecamp core module. `osm_distribution` depends on it; consumer modules need only the SDK, without the distribution GUI. Python consumers use the same packaged engine as the CLI and Basecamp module. Version `0.1.0` exposes the following v1 contract; incompatible contract changes will bump the minor version while the package remains pre-1.0.

## Python embedding

```python
from logos_maps import Client, Config

client = Client(Config.load("/absolute/path/config.local.json"))
entry = client.resolve("germany")
if entry is not None:
    print(entry.cid, entry.version, entry.source_url, entry.parent, entry.level)
    # A consumer may use an already-local PBF in its own module.
    # Retrieval is optional, and needs the native Storage library:
    client.download("germany", "/absolute/path/germany.osm.pbf")
client.close()
```

`resolve` returns the newest snapshot by parsed version, breaking ties by registration timestamp. It returns `None` for an unhosted region and raises `MapsError` for invalid keys, configuration, transport or verification failures. `query` orders entries by registration timestamp, descending. Both work without Geofabrik or wallet keys.

| Method | Return / behavior |
| --- | --- |
| `discover(central=False)` | Frozen regions, hosted state and registered metadata; optional canonical versions |
| `resolve(region)` | `Entry` or `None` |
| `query(region=None, parent=None, cid=None)` | Matching `Entry` list; filters combine with AND |
| `host(region)` | Fetch, verify, store and register one snapshot |
| `bulk_host(regions, exclude=())` | Verify/store selections, then one atomic batch transaction |
| `import_local(region, file)` | Copy, verify against canonical MD5, store and register |
| `batch_register(entries)` | Retrieve pre-uploaded CIDs, verify canonical MD5/version, register atomically |
| `check_updates()` | Entries whose canonical snapshot is newer or not yet hosted |
| `download(region, destination)` | CID download or unhosted fallback, local verification, exclusive output commit |
| `close()` | Stop and release this client's native Storage node |

An `Entry` has `region`, `parent`, `level`, `cid`, `source_url`, `checksum` (MD5), `version` (ISO 8601), `hosted`, `timestamp` (Unix seconds), `sha256` and `size` (bytes). Use `entry.to_dict()` for JSON. The canonical `path` is published by `discover` and `REGIONS`. A consumer using only discovery/resolve/query does not initialize Storage.

## Basecamp embedding

Build and install [examples/consumer](../examples/consumer). Its metadata depends only on `osm_registry`. The minimum worked flow is:

```qml
function decode(value) {
    for (var i=0; i<3 && typeof value === "string"; i++) value=JSON.parse(value)
    return value
}
var configured = decode(logos.callModule("osm_registry", "configure", [configPath]))
var submitted = decode(logos.callModule("osm_registry", "resolve", ["germany"]))
// Save submitted.id; poll that ID periodically, without blocking the UI:
var events = decode(logos.callModule("osm_registry", "poll", [submitted.id]))
// A completed event is {id, success: true, result: Entry | null}.
// Use result.cid and result metadata with your own already-local PBF.
```

`configure(absoluteConfigPath)` validates and remembers the configuration path in the module's host-provided persistence directory. `configure("")` reuses the active connection, then `LOGOS_MAPS_CONFIG`, then the saved path. Success includes `config_path`, a display `label` and `central_enabled`; a first run without a connection returns `{success:false,needs_configuration:true}`. Keys remain in the user's configured wallet, not this connection record. The configured SDK process is shared within Basecamp; reusing the same config does not restart it. Changing config while work is pending is rejected. All operation methods return `{id}` immediately or `{success:false,error}`. `poll(id)` returns only that job's queued progress and completion events, so separate consumers do not steal each other's results. One consumer should own each returned ID.

The Basecamp methods are `discover(bool)`, `resolve(region)`, `query(filtersJson)`, `host(region)`, `bulkHost(selectionJson)`, `importLocal(region,file)`, `download(region,destination)`, `batchRegister(entriesJson)` and `checkUpdates()`. `query` accepts JSON keys `region`, `parent`, `cid`. Bulk selection JSON is `{regions:[...],exclude:[...]}`. `request(requestJson)` is the shared lower-level dispatch API used by the distribution app; its `action` values match the CLI commands.

Progress events have `{id,progress:{phase,...}}`; final events have `{id,success,result}` or `{id,success:false,error}`. Calls are queued in a persistent worker so large PBF transfers keep the GUI responsive, and the native Storage node keeps serving between jobs. The Basecamp host JSON-serializes string return values, which is why the examples decode the outer envelope before the inner JSON.

`python3 scripts/package_sdk.py` builds the deterministic engine archive and bundles the generated registry IDL beside the plugin. Other modules do not need a checkout of this repository. The Basecamp SDK requires a Python 3.9+ interpreter (`LOGOS_MAPS_PYTHON` can select one) and native Storage only for host/download workflows; its module package declares a Storage dependency. Neither analytics nor an external relay is used.
