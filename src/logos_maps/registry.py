"""SPEL wallet submits writes; sequencer RPC supplies authenticated state.

Registry state is Borsh [authority:32][entries_json:String].
"""
import json
import struct
import subprocess
import os
import urllib.request
from pathlib import Path

from .models import Entry, MapsError


def run(arguments, wallet_home=""):
    try:
        environment = os.environ.copy()
        if wallet_home:
            environment["LEE_WALLET_HOME_DIR"] = str(Path(wallet_home).resolve())
        result = subprocess.run(arguments, text=True, capture_output=True, timeout=1800, env=environment)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise MapsError("SPEL command failed: %s" % exc) from exc
    if result.returncode:
        raise MapsError("SPEL rejected transaction: " + result.stderr[-3000:])
    return result.stdout


class Registry:
    def __init__(self, config):
        self.config = config

    def query(self):
        c = self.config
        if not c.registry_account or not c.program_id:
            raise MapsError("Configure program_id and registry_account after deployment")
        body = json.dumps(dict(jsonrpc="2.0", id=1, method="getAccount",
                               params=[c.registry_account])).encode()
        request = urllib.request.Request(c.sequencer_url, body, {"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                reply = json.load(response)
        except (OSError, ValueError) as exc:
            raise MapsError("Cannot read sequencer: %s" % exc) from exc
        if "error" in reply:
            raise MapsError("Sequencer RPC: " + json.dumps(reply["error"]))
        account = reply.get("result", {})
        # This adapter targets SPEL's pinned LEZ v0.2.4 account layout.
        # Refuse other layouts instead of returning misleading empty results.
        if account.get("program_owner") != self._program_words(c.program_id):
            raise MapsError("Registry account is not owned by the configured program")
        raw = account.get("data")
        if not isinstance(raw, list):
            raise MapsError("Unsupported sequencer account layout; expected LEZ v0.2.4 bytes")
        try:
            data = bytes(raw)
            length = struct.unpack_from("<I", data, 32)[0]
            if len(data) != 36 + length:
                raise ValueError("state length mismatch")
            entries = json.loads(data[36:].decode())
            return [Entry(**e).validate() for e in entries]
        except (ValueError, TypeError, struct.error) as exc:
            raise MapsError("Invalid registry state: %s" % exc) from exc

    @staticmethod
    def _program_words(program_id):
        try:
            raw = bytes.fromhex(program_id)
            if len(raw) != 32:
                raise ValueError("length")
            return list(struct.unpack("<8I", raw))
        except ValueError as exc:
            raise MapsError("Program ID must be 64 hexadecimal characters") from exc

    def register(self, entries):
        c = self.config
        if not c.signer or not c.program_id:
            raise MapsError("Configure signer and program_id to register")
        if not 1 <= len(entries) <= 72:
            raise MapsError("A batch must contain 1–72 regions")
        for entry in entries:
            entry.validate()
        payload = json.dumps([e.to_dict() for e in entries], separators=(",", ":")).encode()
        instruction = "register" if len(entries) == 1 else "batch-register"
        output = run([c.spel, "--idl", str(Path(c.idl).resolve()), "--program", c.program_id,
                      "--", instruction, "--authority", c.signer,
                      "--payload", payload.decode("utf-8")], c.wallet_home)
        # Check committed state before declaring success (sequencer may enqueue).
        import time
        for _ in range(30):
            committed = {(e.region, e.cid, e.version) for e in self.query()}
            if all((e.region, e.cid, e.version) in committed for e in entries):
                return {"entries": [e.to_dict() for e in entries], "receipt": output}
            time.sleep(1)
        raise MapsError("Transaction submitted but not confirmed; inspect sequencer before retrying")
