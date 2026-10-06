import dataclasses
import datetime
import json
import re
from pathlib import Path
from importlib import resources
from urllib.parse import urlparse


class MapsError(Exception):
    """An actionable workflow, configuration, or verification failure."""


REGIONS = json.loads(resources.files("logos_maps").joinpath("regions.json").read_text())
BY_REGION = {r["region"]: r for r in REGIONS}


def version_time(value):
    try:
        parsed = datetime.datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            raise ValueError("timezone required")
        return parsed.astimezone(datetime.timezone.utc)
    except (ValueError, AttributeError) as exc:
        raise MapsError("Version must be a dated ISO 8601 snapshot timestamp") from exc


def canonical_source(url):
    parsed = urlparse(url)
    if (parsed.scheme != "https" or parsed.netloc != "download.geofabrik.de"
            or parsed.query or parsed.fragment or not parsed.path.endswith(".osm.pbf")
            or ".." in parsed.path):
        raise MapsError("Snapshot source must be an HTTPS Geofabrik PBF URL")
    return url


@dataclasses.dataclass(frozen=True)
class Entry:
    region: str
    parent: object
    level: str
    cid: str
    source_url: str
    checksum: str
    version: str
    hosted: bool
    timestamp: int
    sha256: str
    size: int

    def validate(self):
        spec = BY_REGION.get(self.region)
        if not spec or (self.parent, self.level) != (spec["parent"], spec["level"]):
            raise MapsError("Region, parent and level must match the frozen partition")
        canonical_source(self.source_url)
        source_path = urlparse(self.source_url).path
        prefix = "/" + spec["path"] + "-"
        if not source_path.startswith(prefix):
            raise MapsError("Source URL does not match the region path")
        suffix = source_path[len(prefix):-len(".osm.pbf")]
        if not re.fullmatch(r"latest|\d{6}", suffix):
            raise MapsError("Source must be a latest or dated Geofabrik snapshot")
        if not re.fullmatch(r"[A-Za-z0-9]{20,160}", self.cid):
            raise MapsError("Storage returned an invalid CID")
        if not re.fullmatch(r"[a-f0-9]{32}", self.checksum):
            raise MapsError("Expected lowercase MD5")
        if not re.fullmatch(r"[a-f0-9]{64}", self.sha256):
            raise MapsError("Expected lowercase SHA256")
        if not isinstance(self.version, str) or len(self.version) > 40:
            raise MapsError("Version must be at most 40 characters")
        parsed_version = version_time(self.version)
        if parsed_version.year < 2000 or parsed_version.year > 2200:
            raise MapsError("Snapshot year must be between 2000 and 2200")
        if type(self.timestamp) is not int or not 1 <= self.timestamp <= 2 ** 64 - 1:
            raise MapsError("Expected a positive timestamp")
        if type(self.size) is not int or not 1 <= self.size <= 2 ** 64 - 1 or self.hosted is not True:
            raise MapsError("Only nonempty, hosted snapshots may be registered")
        return self

    def to_dict(self):
        return dataclasses.asdict(self)


@dataclasses.dataclass
class Config:
    sequencer_url: str = "http://127.0.0.1:3040"
    program_id: str = ""
    registry_account: str = ""
    signer: str = ""
    wallet_home: str = ""
    spel: str = "spel"
    idl: str = "registry/idl.json"
    storage_library: str = ""
    storage_config: object = dataclasses.field(default_factory=dict)
    work_dir: str = ".maps"
    geofabrik: bool = True
    retries: int = 4
    timeout: int = 1800

    def __post_init__(self):
        if type(self.retries) is not int or not 0 <= self.retries <= 8:
            raise MapsError("Storage retries must be between 0 and 8")
        if type(self.timeout) is not int or self.timeout < 1:
            raise MapsError("Storage timeout must be a positive number of seconds")

    @classmethod
    def load(cls, path):
        return cls(**json.loads(Path(path).read_text()))
