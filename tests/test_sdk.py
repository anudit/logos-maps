import copy
import hashlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from logos_maps import Client, Config, Entry, MapsError, REGIONS
from logos_maps.models import BY_REGION
from logos_maps.storage import StorageError

DATA = b"\x00\x00\x00\x0aOSMHeader fixture, not adoption evidence"
MD5 = hashlib.md5(DATA).hexdigest()
CID = "zDvZRwzmAsHGPSv7nbxXFPnWnUtPvRFTVRitqtqAZj6KpxvH3WSY"
VERSION = "2026-10-01T00:00:00Z"


class Response(io.BytesIO):
    def __init__(self, data, headers=None):
        super().__init__(data)
        self.headers = headers or {}


class FakeSource:
    def __init__(self):
        self.calls = []
        self.data = DATA
        self.index = {"features": [{"properties": {"id": r["region"], "timestamp": VERSION,
                     "urls": {"pbf": "https://download.geofabrik.de/" + r["path"] + "-latest.osm.pbf"}}}
                     for r in REGIONS]}

    def __call__(self, url, **_):
        self.calls.append(url)
        if hasattr(url, "get_method") and url.get_method() == "HEAD":
            return Response(b"", {"Last-Modified": "Thu, 01 Oct 2026 00:00:00 GMT"})
        if url.endswith(".json"):
            return Response(json.dumps(self.index).encode())
        if url.endswith(".md5"):
            return Response((MD5 + "  " + url.rsplit("/", 1)[-1][:-4] + "\n").encode())
        return Response(self.data, {"Content-Length": str(len(self.data))})


class FakeStorage:
    def __init__(self):
        self.data = {}
        self.uploads = 0
        self.failures = 0

    def upload(self, file):
        self.uploads += 1
        if self.failures:
            self.failures -= 1
            raise StorageError("temporary connection error")
        self.data[CID] = Path(file).read_bytes()
        return CID

    def download(self, cid, file):
        Path(file).write_bytes(self.data[cid])


class FakeRegistry:
    def __init__(self):
        self.entries = []
        self.batches = []

    def query(self):
        return self.entries

    def register(self, entries):
        self.batches.append(entries)
        self.entries.extend(entries)
        return {"entries": [e.to_dict() for e in entries], "receipt": "test-only"}


class Workflows(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.registry, self.storage, self.source = FakeRegistry(), FakeStorage(), FakeSource()
        self.client = Client(Config(work_dir=self.temp.name), self.registry, self.storage, self.source)

    def test_full_host_query_download_without_central(self):
        self.client.host("germany")
        self.assertEqual(self.client.resolve("germany").checksum, MD5)
        self.assertEqual(len(self.client.query(cid=CID)), 1)
        self.client.config.geofabrik = False
        self.source.calls.clear()
        destination = Path(self.temp.name) / "map.osm.pbf"
        self.assertTrue(self.client.download("germany", destination)["verified"])
        self.assertEqual(destination.read_bytes(), DATA)
        self.assertEqual(self.source.calls, [])
        self.assertTrue(next(r for r in self.client.discover() if r["region"] == "germany")["hosted"])

    def test_bulk_opt_out_uses_one_transaction(self):
        self.client.bulk_host(["germany", "france", "germany", "us/california"], exclude=["france"])
        self.assertEqual(len(self.registry.batches), 1)
        self.assertEqual([e.region for e in self.registry.entries], ["germany", "us/california"])
        self.assertEqual(len(self.client.query(parent="us")), 1)

    def test_corrupt_import_never_uploads_or_registers(self):
        file = Path(self.temp.name) / "bad.osm.pbf"
        file.write_bytes(b"corrupt")
        with self.assertRaisesRegex(MapsError, "Checksum mismatch"):
            self.client.import_local("germany", file)
        self.assertEqual(self.storage.uploads, 0)
        self.assertEqual(self.registry.batches, [])

    def test_import_uses_staged_copy(self):
        file = Path(self.temp.name) / "good.osm.pbf"
        file.write_bytes(DATA)
        self.client.import_local("germany", file)
        self.assertEqual(self.storage.data[CID], DATA)

    def test_host_corruption_fails_and_bulk_not_registered(self):
        self.source.data = b"bad"
        with self.assertRaisesRegex(MapsError, "Checksum mismatch"):
            self.client.bulk_host(["germany", "france"])
        self.assertEqual(self.registry.batches, [])

    def test_fallback_download_verified(self):
        result = self.client.download("germany", Path(self.temp.name) / "fallback")
        self.assertEqual(result["source"], "geofabrik")

    def test_corrupt_hosted_download_removes_partial(self):
        self.client.host("germany")
        self.storage.data[CID] = b"bad"
        destination = Path(self.temp.name) / "download"
        with self.assertRaisesRegex(MapsError, "SHA256"):
            self.client.download("germany", destination)
        self.assertFalse(destination.exists())
        self.assertEqual(list(Path(self.temp.name).glob("*.part")), [])

    def test_existing_file_is_preserved(self):
        destination = Path(self.temp.name) / "existing"
        destination.write_bytes(b"keep")
        with self.assertRaisesRegex(MapsError, "already exists"):
            self.client.download("germany", destination)
        self.assertEqual(destination.read_bytes(), b"keep")

    def test_retry_exponential_backoff_and_exhaustion(self):
        self.storage.failures = 2
        with patch("logos_maps.sdk.time.sleep") as sleep:
            self.client.host("germany")
        self.assertEqual([c.args[0] for c in sleep.call_args_list], [1, 2])
        self.storage.failures = 100
        with patch("logos_maps.sdk.time.sleep"), self.assertRaisesRegex(MapsError, "5 attempt"):
            self.client.host("france")
        self.assertEqual(len(self.registry.batches), 1)

    def test_partition_exact_and_nonoverlapping(self):
        self.assertEqual(len(REGIONS), 72)
        self.assertEqual(len(BY_REGION), 72)
        paths = [r["path"] for r in REGIONS]
        self.assertFalse(any(a != b and b.startswith(a + "/") for a in paths for b in paths))
        for parent in ("us", "india", "china", "russia"):
            with self.assertRaises(MapsError):
                self.client.host(parent)

    def test_update_comparison_uses_region_and_version(self):
        self.client.host("germany")
        updates = self.client.check_updates()
        self.assertNotIn("germany", [u["region"] for u in updates])
        for feature in self.source.index["features"]:
            if feature["properties"]["id"] == "germany":
                feature["properties"]["timestamp"] = "2026-10-02T00:00:00Z"
        self.assertIn("germany", [u["region"] for u in self.client.check_updates()])

    def test_disabled_central_and_missing_region(self):
        self.client.config.geofabrik = False
        with self.assertRaisesRegex(MapsError, "disabled"):
            self.client.host("germany")
        self.client.config.geofabrik = True
        self.source.index = {"features": []}
        with self.assertRaisesRegex(MapsError, "unavailable"):
            self.client.host("germany")


if __name__ == "__main__":
    unittest.main()
