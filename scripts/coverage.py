#!/usr/bin/env python3
"""Re-fetch registered CIDs and evaluate the 15-country/25-region floors.
Only matching Geofabrik MD5, registry SHA256 and size contribute.
"""
import argparse
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from logos_maps import Client, Config, MapsError
from logos_maps.models import version_time
from logos_maps.sdk import hashes


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default="config.local.json")
    parser.add_argument("--output", default="evidence/coverage.json")
    args = parser.parse_args()
    client = Client(Config.load(args.config))
    verified, failed = [], []
    try:
        for region in client.discover():
            entry = client.resolve(region["region"])
            if not entry:
                continue
            try:
                expected = client._checksum(entry.source_url)
                if version_time(client._head_version(entry.source_url)) != version_time(entry.version):
                    raise MapsError("Snapshot changed; verify against its archived snapshot URL")
                with tempfile.TemporaryDirectory() as temporary:
                    file = Path(temporary) / "map.osm.pbf"
                    client.storage.download(entry.cid, file)
                    md5, sha, size = hashes(file)
                    if (md5, sha, size) != (expected, entry.sha256, entry.size) or md5 != entry.checksum:
                        raise MapsError("CID bytes do not match Geofabrik and registry metadata")
                verified.append(entry.to_dict())
            except (MapsError, OSError) as exc:
                failed.append({"region": entry.region, "error": str(exc)})
        countries = sorted({entry["parent"] or entry["region"] for entry in verified})
        report = {"sequencer": client.config.sequencer_url, "program_id": client.config.program_id,
                  "verified_entries": verified, "failed": failed, "countries": countries,
                  "country_count": len(countries), "entry_count": len(verified),
                  "meets_required_floors": len(countries) >= 15 and len(verified) >= 25}
        Path(args.output).write_text(json.dumps(report, indent=2) + "\n")
        print("%s verified regions across %s countries" % (len(verified), len(countries)))
        return 0 if report["meets_required_floors"] else 1
    finally:
        client.close()


if __name__ == "__main__":
    raise SystemExit(main())
