"""Real Logos Storage test, opt-in when the native library is available."""
import os
import tempfile
import unittest
from pathlib import Path

from logos_maps.storage import NativeStorage


@unittest.skipUnless(os.getenv("LOGOS_STORAGE_LIBRARY"), "Set LOGOS_STORAGE_LIBRARY for native test")
class NativeRoundTrip(unittest.TestCase):
    def test_real_content_addressed_round_trip(self):
        with tempfile.TemporaryDirectory() as directory:
            data = bytes(range(256)) * 1024  # spans several native blocks
            source, target = Path(directory) / "map", Path(directory) / "download"
            source.write_bytes(data)
            config = {"data-dir": directory + "/node", "listen-ip": "127.0.0.1",
                      "no-bootstrap-node": True, "nat": "extip:127.0.0.1"}
            with NativeStorage(os.environ["LOGOS_STORAGE_LIBRARY"], config, timeout=60) as storage:
                cid = storage.upload(source)
                self.assertTrue(cid.startswith("z"))
                storage.download(cid, target)
                self.assertEqual(target.read_bytes(), data)
