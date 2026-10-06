import datetime
import hashlib
import json
import os
import re
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

from .models import BY_REGION, REGIONS, Entry, MapsError, version_time, canonical_source
from .registry import Registry
from .storage import NativeStorage, StorageError

INDEX = "https://download.geofabrik.de/index-v1-nogeom.json"


def hashes(file):
    md5, sha = hashlib.md5(), hashlib.sha256()
    size = 0
    with open(file, "rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            md5.update(block)
            sha.update(block)
            size += len(block)
    return md5.hexdigest(), sha.hexdigest(), size


class Client:
    """Full registry API. Inject transports for tests or embedded environments."""
    def __init__(self, config, registry=None, storage=None, opener=None, progress=None):
        self.config = config
        self.registry = registry or Registry(config)
        self._storage = storage
        self.opener = opener or urllib.request.urlopen
        self.progress = progress or (lambda event: None)

    @property
    def storage(self):
        if self._storage is None:
            config = dict(self.config.storage_config)
            config.setdefault("data-dir", str(Path(self.config.work_dir).resolve() / "storage"))
            config.setdefault("network", "logos.test")
            self._storage = NativeStorage(self.config.storage_library, config, self.config.timeout,
                                          lambda msg: self.progress({"storage": msg}))
        return self._storage

    def close(self):
        if self._storage is not None and hasattr(self._storage, "close"):
            self._storage.close()

    def query(self, region=None, parent=None, cid=None):
        entries = self.registry.query()
        return sorted((e for e in entries if (region is None or e.region == region)
                       and (parent is None or e.parent == parent)
                       and (cid is None or e.cid == cid)),
                      key=lambda e: (e.timestamp, version_time(e.version)), reverse=True)

    def resolve(self, region):
        self._spec(region)
        entries = self.query(region=region)
        if not entries:
            return None
        return max(entries, key=lambda e: (version_time(e.version), e.timestamp))

    def discover(self, central=False):
        """Registry discovery works offline from Geofabrik; central is explicit."""
        hosted = self.query()
        latest = {}
        for entry in hosted:
            old = latest.get(entry.region)
            if old is None or version_time(entry.version) > version_time(old.version):
                latest[entry.region] = entry
        index = self.central_index() if central else {}
        return [dict(spec, hosted=spec["region"] in latest,
                     registered=latest[spec["region"]].to_dict() if spec["region"] in latest else None,
                     central=index.get(spec["region"]),
                     available=(spec["region"] in index) if central else None) for spec in REGIONS]

    def _central(self):
        if not self.config.geofabrik:
            raise MapsError("Geofabrik is disabled; hosted discovery and downloads still work")

    def central_index(self, selected=None):
        self._central()
        try:
            with self.opener(INDEX, timeout=30) as response:
                index = json.load(response)
        except (OSError, ValueError) as exc:
            raise MapsError("Cannot fetch Geofabrik index: %s" % exc) from exc
        by_path = {}
        for feature in index["features"]:
            props = feature["properties"]
            url = props.get("urls", {}).get("pbf", "")
            if url.startswith("https://download.geofabrik.de/"):
                by_path[url[len("https://download.geofabrik.de/"):-len("-latest.osm.pbf")]] = props
        result = {}
        for spec in REGIONS:
            if selected is not None and spec["region"] not in selected:
                continue
            props = by_path.get(spec["path"])
            if props:
                version = props.get("timestamp")
                # The index commonly has no timestamp. A Last-Modified HEAD
                # is the canonical snapshot's version, not the index mtime.
                url = canonical_source(props["urls"]["pbf"])
                if not version:
                    version = self._head_version(url)
                version_time(version)
                result[spec["region"]] = {"source_url": url, "version": version}
        return result

    def _head_version(self, url):
        from email.utils import parsedate_to_datetime
        try:
            with self.opener(urllib.request.Request(url, method="HEAD"), timeout=30) as response:
                return parsedate_to_datetime(response.headers["Last-Modified"]).isoformat()
        except (OSError, TypeError, ValueError) as exc:
            raise MapsError("Cannot determine snapshot version for " + url) from exc

    def check_updates(self):
        index = self.central_index()
        latest = {r["region"]: r["registered"] for r in self.discover()}
        return [dict(region=region, registered=latest[region], central=metadata)
                for region, metadata in index.items()
                if latest[region] is None or version_time(metadata["version"]) >
                version_time(latest[region]["version"])]

    @staticmethod
    def _spec(region):
        if region not in BY_REGION:
            raise MapsError("Unknown region or excluded parent: " + region)
        return BY_REGION[region]

    def _checksum(self, url):
        self._central()
        try:
            with self.opener(url + ".md5", timeout=30) as response:
                text = response.read(4096).decode("ascii")
            match = re.fullmatch(r"([a-fA-F0-9]{32})\s+\*?([^\r\n]+)\s*", text.strip())
            if not match or Path(match[2]).name != Path(url).name:
                raise ValueError("checksum filename does not match snapshot")
            return match[1].lower()
        except (OSError, ValueError) as exc:
            raise MapsError("Cannot read Geofabrik checksum: %s" % exc) from exc

    def _fetch(self, url, destination):
        try:
            with self.opener(url, timeout=60) as response, open(destination, "wb") as output:
                total = response.headers.get("Content-Length")
                copied = 0
                for chunk in iter(lambda: response.read(1024 * 1024), b""):
                    output.write(chunk)
                    copied += len(chunk)
                    self.progress({"phase": "fetch", "bytes": copied, "total": total})
                if total is not None and copied != int(total):
                    raise MapsError("Snapshot transfer was truncated")
        except OSError as exc:
            raise MapsError("Snapshot download failed: %s" % exc) from exc

    def _snapshot(self, region, index):
        self._spec(region)
        if region not in index:
            raise MapsError("Frozen region is unavailable in the current Geofabrik index: " + region)
        snapshot = dict(index[region])
        # Prefer the immutable archived URL when it is the same publication.
        # Keep latest if Geofabrik has not materialized its dated counterpart.
        latest = snapshot["source_url"]
        dated = latest.replace("-latest.osm.pbf", "-" +
                               version_time(snapshot["version"]).strftime("%y%m%d") + ".osm.pbf")
        if dated != latest:
            try:
                if version_time(self._head_version(dated)) == version_time(snapshot["version"]):
                    snapshot["source_url"] = dated
            except MapsError:
                pass
        return snapshot

    def _upload(self, file):
        for attempt in range(self.config.retries + 1):
            try:
                return self.storage.upload(file)
            except StorageError as exc:
                # Retry only transient transport errors; never permanent errors.
                transient = any(word in str(exc).lower() for word in
                                ("timeout", "timed out", "connection", "temporar", "unavailable"))
                if not transient or attempt == self.config.retries:
                    raise MapsError("Storage upload failed after %s attempt(s): %s" %
                                    (attempt + 1, exc)) from exc
                self.progress({"phase": "retry", "attempt": attempt + 1, "delay": 2 ** attempt})
                time.sleep(2 ** attempt)

    def _prepare(self, region, file, snapshot):
        spec = self._spec(region)
        url = snapshot["source_url"]
        expected = self._checksum(url)
        actual, sha, size = hashes(file)
        if actual != expected:
            raise MapsError("Checksum mismatch for %s: expected %s, got %s; nothing registered" %
                            (region, expected, actual))
        if version_time(self._head_version(url)) != version_time(snapshot["version"]):
            raise MapsError("Geofabrik snapshot changed during transfer; retry with the new version")
        self.progress({"phase": "verified", "region": region, "checksum": actual})
        cid = self._upload(file)
        return Entry(region, spec["parent"], spec["level"], cid, url, actual,
                     snapshot["version"], True, int(time.time()), sha, size).validate()

    def import_local(self, region, file):
        snapshot = self._snapshot(region, self.central_index([region]))
        # Copy first so another process cannot change bytes between hash/upload.
        import shutil
        with self._temporary() as temp:
            staged = Path(temp) / "snapshot.osm.pbf"
            shutil.copyfile(file, staged)
            return self._register_verified([self._prepare(region, staged, snapshot)])

    def _temporary(self):
        work = Path(self.config.work_dir)
        work.mkdir(parents=True, exist_ok=True)
        return tempfile.TemporaryDirectory(dir=work)

    def host(self, region):
        return self.bulk_host([region])

    def bulk_host(self, regions, exclude=()):
        selected = list(dict.fromkeys(r for r in regions if r not in exclude))
        if not selected:
            raise MapsError("No regions selected")
        for region in selected:
            self._spec(region)
        index = self.central_index(selected)
        entries = []
        for region in selected:
            snapshot = self._snapshot(region, index)
            with self._temporary() as temp:
                file = Path(temp) / "snapshot.osm.pbf"
                self._fetch(snapshot["source_url"], file)
                entries.append(self._prepare(region, file, snapshot))
        # One atomic on-chain transaction, even though uploads are sequential.
        return self._register_verified(entries)

    def batch_register(self, entries):
        """Verify pre-uploaded CIDs against Geofabrik before registering."""
        entries = [Entry(**e) if isinstance(e, dict) else e for e in entries]
        self._validate_batch(entries)
        for entry in entries:
            if self._checksum(entry.source_url) != entry.checksum:
                raise MapsError("Batch checksum does not match Geofabrik for " + entry.region)
            if version_time(self._head_version(entry.source_url)) != version_time(entry.version):
                raise MapsError("Batch version does not match Geofabrik for " + entry.region)
            with self._temporary() as temp:
                file = Path(temp) / "snapshot.osm.pbf"
                self.storage.download(entry.cid, file)
                if hashes(file) != (entry.checksum, entry.sha256, entry.size):
                    raise MapsError("Batch CID bytes do not match verified metadata for " + entry.region)
        return self.registry.register(entries)

    @staticmethod
    def _validate_batch(entries):
        if not 1 <= len(entries) <= 72:
            raise MapsError("A batch must contain 1–72 regions")
        if len({e.region for e in entries}) != len(entries):
            raise MapsError("A batch cannot repeat a region")
        for entry in entries:
            entry.validate()

    def _register_verified(self, entries):
        self._validate_batch(entries)
        return self.registry.register(entries)

    def download(self, region, destination):
        self._spec(region)
        destination = Path(destination).expanduser().resolve()
        if destination.exists():
            raise MapsError("Destination already exists; choose a new path")
        destination.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(prefix=".maps-", suffix=".part", dir=destination.parent)
        os.close(fd)
        try:
            entry = self.resolve(region)
            if entry:
                self.storage.download(entry.cid, temporary)
                # Storage verifies the CID/Merkle blocks. A second local SHA256
                # validates the reconstructed stream; no Geofabrik contact.
                _, sha, size = hashes(temporary)
                if sha != entry.sha256 or size != entry.size:
                    raise MapsError("Downloaded bytes fail registry SHA256/size verification")
                result = {"source": "logos-storage", "entry": entry.to_dict(), "verified": True}
            else:
                snapshot = self._snapshot(region, self.central_index([region]))
                expected = self._checksum(snapshot["source_url"])
                self._fetch(snapshot["source_url"], temporary)
                if hashes(temporary)[0] != expected:
                    raise MapsError("Direct fallback checksum mismatch")
                result = {"source": "geofabrik", "verified": True, **snapshot}
            # Hard-link creates destination exclusively, without overwriting a
            # concurrent file. Temporary and destination are on the same FS.
            os.link(temporary, destination)
            return dict(result, path=str(destination))
        finally:
            Path(temporary).unlink(missing_ok=True)
