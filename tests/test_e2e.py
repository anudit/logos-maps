"""Real sequencer + real native Storage. Canonical HTTP is a deterministic
fixture so CI avoids multi-GB downloads; these entries NEVER count as coverage.
"""
import os
import tempfile
import unittest
from pathlib import Path

from logos_maps import Client, Config
from test_sdk import DATA, FakeSource


@unittest.skipUnless(os.getenv("LOGOS_MAPS_E2E_CONFIG"), "Run scripts/integration.py for real sequencer E2E")
class StandalonePipeline(unittest.TestCase):
    def test_host_query_download_and_atomic_batch(self):
        config = Config.load(os.environ["LOGOS_MAPS_E2E_CONFIG"])
        client = Client(config, opener=FakeSource())
        self.addCleanup(client.close)
        result = client.host("germany")
        entry = client.resolve("germany")
        self.assertEqual(entry.cid, result["entries"][0]["cid"])
        self.assertEqual(client.query(cid=entry.cid)[0].region, "germany")
        config.geofabrik = False
        with tempfile.TemporaryDirectory() as directory:
            file = Path(directory) / "germany.osm.pbf"
            self.assertTrue(client.download("germany", file)["verified"])
            self.assertEqual(file.read_bytes(), DATA)
        config.geofabrik = True
        batch = client.bulk_host(["france", "us/california"])
        self.assertEqual(len(batch["entries"]), 2)
        self.assertEqual(client.query(parent="us")[0].region, "us/california")
        self.assertIsNotNone(client.resolve("france"))
