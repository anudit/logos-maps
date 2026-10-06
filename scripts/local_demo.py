#!/usr/bin/env python3
"""Run the local fixture demo in the foreground; Ctrl-C stops its node."""
import sys
from pathlib import Path
import integration

root = Path(__file__).resolve().parents[1]
if len(sys.argv) > 1:
    raise SystemExit("Usage: python3 scripts/local_demo.py (no arguments)")
sys.argv += ["--demo", "--port", "33341", "--lez-source", str(root / ".tools"),
             "--sequencer", str(root / ".tools/bin/sequencer_service"),
             "--wallet", str(root / ".tools/bin/wallet"),
             "--spel", str(root / ".tools/bin/spel"),
             "--r0vm", str(root / ".tools/risc0/extensions/v3.0.5-cargo-risczero-aarch64-apple-darwin/r0vm"),
             "--storage-library", "/Applications/LogosBasecamp.app/Contents/modules/storage_module/libstorage.dylib"]
integration.main()
