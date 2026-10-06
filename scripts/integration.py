#!/usr/bin/env python3
"""Start a real standalone LEZ in an isolated temporary home and test the SDK.
Requires a built LEZ v0.2.4 checkout, SPEL, r0vm 3.0.5, and native libstorage.
No public testnet writes. No fixtures are reported as adoption evidence.
"""
import argparse
import contextlib
import json
import os
import re
import subprocess
import shutil
import tempfile
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lez-source", required=True, type=Path)
    parser.add_argument("--storage-library", required=True, type=Path)
    parser.add_argument("--spel", default="spel")
    parser.add_argument("--wallet", default="wallet")
    parser.add_argument("--r0vm", default="r0vm")
    parser.add_argument("--port", default=33340, type=int)
    parser.add_argument("--program-bin", type=Path)
    parser.add_argument("--demo", action="store_true", help="Keep the fixture node running for interactive local use")
    parser.add_argument("--sequencer", type=Path)
    args = parser.parse_args()
    args.lez_source = args.lez_source.resolve()
    for name in ("spel", "wallet", "r0vm"):
        value = getattr(args, name)
        resolved = shutil.which(value) or str(Path(value).resolve())
        if not Path(resolved).is_file():
            raise RuntimeError("Missing executable: " + value)
        setattr(args, name, resolved)
    binary = args.program_bin or next((ROOT / "registry/methods/target").rglob("osm_registry.bin"))
    work = ROOT / ".maps"
    work.mkdir(exist_ok=True)
    context = (contextlib.nullcontext(tempfile.mkdtemp(prefix="demo-", dir=work)) if args.demo
               else tempfile.TemporaryDirectory(prefix="e2e-", dir=work))
    with context as temporary:
        directory = Path(temporary)
        wallet_home = directory / "wallet"
        wallet_home.mkdir(mode=0o700)
        url = "http://127.0.0.1:%s" % args.port
        config = json.loads((args.lez_source / "lez/sequencer/service/configs/debug/sequencer_config.json").read_text())
        config.update(home=str(directory / "sequencer"), block_create_timeout="1s", metrics_address=None)
        (directory / "sequencer.json").write_text(json.dumps(config))
        wallet_config = {"sequencers": [{"sequencer_addr": url}], "seq_poll_timeout": "1s",
                         "seq_tx_poll_max_blocks": 30, "seq_poll_max_retries": 3,
                         "seq_block_poll_max_amount": 100,
                         "multi_sequencer_client_config": {"distribution_limit": 1, "calibration_limit": 100}}
        (wallet_home / "wallet_config.json").write_text(json.dumps(wallet_config))
        env = dict(os.environ, RISC0_DEV_MODE="1", RISC0_SERVER_PATH=str(Path(args.r0vm).resolve()),
                   LEE_WALLET_HOME_DIR=str(wallet_home), PYTHONPATH=str(ROOT / "src"))

        def run(command, name, private=False):
            result = subprocess.run(command, env=env, capture_output=True, text=True,
                                    input="\n", timeout=600, cwd=ROOT)
            log = directory / (name + ".log")
            log.write_text(result.stdout + result.stderr)
            if private:
                log.chmod(0o600)
            if result.returncode:
                raise RuntimeError("%s failed; %s" % (name, "private wallet log" if private else result.stderr[-3000:]))
            return result.stdout

        with (directory / "sequencer.log").open("w") as log:
            sequencer = subprocess.Popen([str(args.sequencer or args.lez_source / "target/release/sequencer_service"),
                str(directory / "sequencer.json"), "--listen-address", "127.0.0.1", "--port", str(args.port)],
                env=env, stdout=log, stderr=log)
            try:
                deadline = time.monotonic() + 60
                while True:
                    if sequencer.poll() is not None:
                        raise RuntimeError("Sequencer stopped: " + (directory / "sequencer.log").read_text()[-3000:])
                    try:
                        body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "checkHealth", "params": []}).encode()
                        with urllib.request.urlopen(urllib.request.Request(url, body,
                            {"Content-Type": "application/json"}), timeout=1) as response:
                            if "result" in json.load(response):
                                break
                    except OSError:
                        pass
                    if time.monotonic() > deadline:
                        raise RuntimeError("Sequencer health timeout")
                    time.sleep(0.2)
                output = run([args.wallet, "account", "new", "public", "--label", "e2e-curator"], "wallet-create", private=True)
                account = re.search(r"Generated new account with account_id Public/([A-Za-z0-9]+)", output)[1]
                for path in wallet_home.iterdir():
                    path.chmod(0o600)
                run([args.wallet, "auth-transfer", "init", "--account-id", "Public/" + account], "wallet-init")
                run([args.wallet, "pinata", "claim", "--to", "Public/" + account], "wallet-fund")
                run([args.wallet, "deploy-program", str(binary)], "deploy")
                program = run([args.spel, "program-id", str(binary), "--format", "hex"], "program-id").strip()
                base = [args.spel, "--idl", str(ROOT / "registry/idl.json"), "--program", program]
                registry = run(base + ["pda", "state"], "pda").strip()
                run(base + ["--", "initialize", "--authority", account], "registry-init")
                sdk_config = dict(sequencer_url=url, program_id=program, registry_account=registry,
                    signer=account, wallet_home=str(wallet_home), spel=str(Path(args.spel).resolve()),
                    idl=str(ROOT / "registry/idl.json"), work_dir=str(directory),
                    storage_library=str(args.storage_library.resolve()),
                    storage_config={"listen-ip": "127.0.0.1", "no-bootstrap-node": True, "nat": "extip:127.0.0.1"})
                config_path = directory / "client.json"
                config_path.write_text(json.dumps(sdk_config))
                env["LOGOS_MAPS_E2E_CONFIG"] = str(config_path)
                run([os.sys.executable, "-m", "unittest", "discover", "-s", "tests", "-p", "test_e2e.py", "-v"], "pipeline")
                evidence = {"network": "standalone", "proof_mode": "RISC0_DEV_MODE=1",
                            "fixture_bytes": True, "adoption_coverage": False,
                            "program_id": program, "registry_account": registry,
                            "host_query_download": "passed", "atomic_batch": "passed"}
                (ROOT / "evidence/standalone.json").write_text(json.dumps(evidence, indent=2) + "\n")
                print("Real standalone pipeline and atomic batch passed", flush=True)
                if args.demo:
                    sdk_config["geofabrik"] = False
                    demo_config = ROOT / ".maps/demo-config.json"
                    demo_config.write_text(json.dumps(sdk_config, indent=2) + "\n")
                    demo_config.chmod(0o600)
                    print("Local demo ready: " + str(demo_config), flush=True)
                    print("Germany, France and California contain tiny TEST FIXTURES, not usable maps. Ctrl-C stops the node.", flush=True)
                    try:
                        sequencer.wait()
                    except KeyboardInterrupt:
                        pass
            finally:
                sequencer.terminate()
                try:
                    sequencer.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    sequencer.kill()
                    sequencer.wait()


if __name__ == "__main__":
    main()
