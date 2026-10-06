#!/usr/bin/env python3
"""Check the frozen JSON/Rust partition parity and hierarchy invariants."""
import json
from pathlib import Path

root = Path(__file__).resolve().parents[1]
regions = json.loads((root / "src/logos_maps/regions.json").read_text())
assert len(regions) == 72
assert len({r["region"] for r in regions}) == 72
assert sum(r["level"] == "country" for r in regions) == 48
assert {p: sum(r["parent"] == p for r in regions) for p in ("us", "india", "china", "russia")} == {
    "us": 8, "india": 6, "china": 6, "russia": 4}
source = (root / "registry/src/regions.rs").read_text()
for region in regions:
    parent = "None" if region["parent"] is None else "Some(" + json.dumps(region["parent"]) + ")"
    row = "(%s, %s, %s, %s)," % (json.dumps(region["region"]), parent,
                                json.dumps(region["level"]), json.dumps(region["path"]))
    assert row in source, "Rust partition differs: " + region["region"]
paths = [r["path"] for r in regions]
assert not any(b.startswith(a + "/") for a in paths for b in paths if a != b)
print("72 frozen regions: JSON/Rust parity and non-overlap passed")
