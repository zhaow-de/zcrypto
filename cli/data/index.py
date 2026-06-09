from __future__ import annotations

import dataclasses as dc
import datetime as dt
import hashlib
import json
import os
from pathlib import Path


@dc.dataclass
class FileEntry:
    sha256: str
    updated_at: str

    def to_dict(self) -> dict:
        return {"sha256": self.sha256, "updated_at": self.updated_at}

    @classmethod
    def from_dict(cls, d: dict) -> "FileEntry":
        return cls(sha256=d["sha256"], updated_at=d["updated_at"])


@dc.dataclass
class FieldEntry:
    bin: str
    sha256: str
    updated_at: str

    def to_dict(self) -> dict:
        return {"bin": self.bin, "sha256": self.sha256, "updated_at": self.updated_at}

    @classmethod
    def from_dict(cls, d: dict) -> "FieldEntry":
        return cls(bin=d["bin"], sha256=d["sha256"], updated_at=d["updated_at"])


@dc.dataclass
class PairIntervalEntry:
    from_date: str  # ISO YYYY-MM-DD
    rows: int
    fields: dict[str, FieldEntry]

    def to_dict(self) -> dict:
        return {
            "from": self.from_date,
            "rows": self.rows,
            "fields": {k: v.to_dict() for k, v in self.fields.items()},
        }

    @classmethod
    def from_dict(cls, d: dict) -> "PairIntervalEntry":
        return cls(
            from_date=d["from"],
            rows=int(d["rows"]),
            fields={k: FieldEntry.from_dict(v) for k, v in d["fields"].items()},
        )


@dc.dataclass
class PairEntry:
    base_asset: str
    quote_asset: str
    intervals: dict[str, PairIntervalEntry]

    def to_dict(self) -> dict:
        return {
            "base_asset": self.base_asset,
            "quote_asset": self.quote_asset,
            "intervals": {k: v.to_dict() for k, v in self.intervals.items()},
        }

    @classmethod
    def from_dict(cls, d: dict) -> "PairEntry":
        return cls(
            base_asset=d["base_asset"],
            quote_asset=d["quote_asset"],
            intervals={k: PairIntervalEntry.from_dict(v) for k, v in d["intervals"].items()},
        )


@dc.dataclass
class CalendarEntry:
    freq: str
    from_date: str
    to_date: str
    days: int

    def to_dict(self) -> dict:
        return {"freq": self.freq, "from": self.from_date, "to": self.to_date, "days": self.days}

    @classmethod
    def from_dict(cls, d: dict) -> "CalendarEntry":
        return cls(freq=d["freq"], from_date=d["from"], to_date=d["to"], days=int(d["days"]))


@dc.dataclass
class IndexData:
    schema_version: int
    updated_at: str
    calendar: CalendarEntry
    pairs: dict[str, PairEntry]
    other_files: dict[str, FileEntry]

    def to_dict(self) -> dict:
        return {
            "schema_version": self.schema_version,
            "updated_at": self.updated_at,
            "calendar": self.calendar.to_dict(),
            "pairs": {k: v.to_dict() for k, v in self.pairs.items()},
            "other_files": {k: v.to_dict() for k, v in self.other_files.items()},
        }

    @classmethod
    def from_dict(cls, d: dict) -> "IndexData":
        return cls(
            schema_version=int(d["schema_version"]),
            updated_at=d["updated_at"],
            calendar=CalendarEntry.from_dict(d["calendar"]),
            pairs={k: PairEntry.from_dict(v) for k, v in d["pairs"].items()},
            other_files={k: FileEntry.from_dict(v) for k, v in d["other_files"].items()},
        )


def load_index(out_dir: Path) -> IndexData | None:
    p = out_dir / "index.json"
    if not p.exists():
        return None
    return IndexData.from_dict(json.loads(p.read_text(encoding="utf-8")))


def save_index(out_dir: Path, index: IndexData) -> None:
    """Atomic write: serialize to a sibling tmp file, then `os.replace` over the target."""
    target = out_dir / "index.json"
    tmp = target.with_suffix(target.suffix + ".tmp")
    tmp.write_text(json.dumps(index.to_dict(), indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, target)


def compute_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def utc_now_iso() -> str:
    return dt.datetime.now(tz=dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
