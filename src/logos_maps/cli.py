import argparse
import json
import signal
import sys
import time
from pathlib import Path

from .models import Config, MapsError, REGIONS
from .sdk import Client


def dispatch(client, request):
    action = request["action"]
    if action == "regions":
        return REGIONS
    if action == "discover":
        return client.discover(request.get("central", False))
    if action == "query":
        return [e.to_dict() for e in client.query(**{k: request[k] for k in
                ("region", "parent", "cid") if request.get(k)})]
    if action == "resolve":
        entry = client.resolve(request["region"])
        return entry.to_dict() if entry else None
    if action == "host":
        return client.host(request["region"])
    if action == "bulk-host":
        return client.bulk_host(request["regions"], request.get("exclude", []))
    if action == "batch-register":
        return client.batch_register(request["entries"])
    if action == "updates":
        return client.check_updates()
    if action == "download":
        return client.download(request["region"], request["destination"])
    if action == "import":
        return client.import_local(request["region"], request["file"])
    raise MapsError("Unknown action: " + action)


def worker(config):
    """Persistent JSON-lines process: node stays alive between GUI jobs."""
    def send(payload):
        print(json.dumps(payload), flush=True)

    active_id = None
    client = Client(config, progress=lambda event: send({"id": active_id, "progress": event}))
    try:
        for line in sys.stdin:
            request = {}
            try:
                request = json.loads(line)
                if not isinstance(request, dict):
                    request = {}
                    raise MapsError("Request must be a JSON object")
                active_id = request.get("id")
                result = dispatch(client, request)
                send({"id": request.get("id"), "success": True, "result": result})
            except (MapsError, OSError, ValueError, KeyError, TypeError) as exc:
                send({"id": request.get("id"), "success": False, "error": str(exc)})
    finally:
        client.close()


def main():
    parser = argparse.ArgumentParser(description="Verified OSM distribution on Logos")
    parser.add_argument("--config", default="config.local.json")
    commands = parser.add_subparsers(dest="action", required=True)
    commands.add_parser("regions", help="Print the frozen partition (no network)")
    discovery = commands.add_parser("discover")
    discovery.add_argument("--central", action="store_true")
    lookup = commands.add_parser("query")
    for key in ("region", "parent", "cid"):
        lookup.add_argument("--" + key)
    for action in ("resolve", "host"):
        commands.add_parser(action).add_argument("region")
    bulk = commands.add_parser("bulk-host")
    bulk.add_argument("regions", nargs="+")
    bulk.add_argument("--exclude", action="append", default=[])
    batch = commands.add_parser("batch-register")
    batch.add_argument("file", help="JSON array of verified, uploaded entries")
    commands.add_parser("updates")
    download = commands.add_parser("download")
    download.add_argument("region")
    download.add_argument("destination")
    local = commands.add_parser("import")
    local.add_argument("region")
    local.add_argument("file")
    commands.add_parser("worker", help=argparse.SUPPRESS)
    commands.add_parser("serve", help="Keep your Storage mirror running")
    args = vars(parser.parse_args())
    config_path = args.pop("config")
    client = None
    try:
        config = Config.load(config_path) if args["action"] != "regions" else Config()
        if args["action"] == "worker":
            worker(config)
            return
        client = Client(config, progress=lambda e: print(json.dumps(e), file=sys.stderr, flush=True))
        if args["action"] == "serve":
            client.storage
            print("Storage mirror running; Ctrl-C to stop", file=sys.stderr)
            while True:
                time.sleep(1)
        if args["action"] == "batch-register":
            args["entries"] = json.loads(Path(args.pop("file")).read_text())
        print(json.dumps(dispatch(client, args), indent=2))
    except KeyboardInterrupt:
        pass
    except (MapsError, OSError, ValueError, TypeError) as exc:
        print("error: " + str(exc), file=sys.stderr)
        raise SystemExit(1)
    finally:
        if client:
            client.close()


if __name__ == "__main__":
    main()
