"""Pre-registered trial register for the deflated Sharpe computation."""

from __future__ import annotations

import dataclasses
import hashlib
import json
import uuid
from pathlib import Path


def recipe_config_hash(recipe) -> str:
    """Return a stable sha256 hex digest of a Recipe's frozen config.

    Serialization: ``json.dumps(dataclasses.asdict(recipe), sort_keys=True, default=str)``,
    encoded utf-8.  Same recipe → same hash across calls/processes.
    """
    payload = json.dumps(dataclasses.asdict(recipe), sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def register_trial(
    path: Path,
    *,
    recipe_name: str,
    config_hash: str,
    sharpe: float,
    created: str,
) -> None:
    """Append one JSON line to *path*, creating parent directories as needed.

    Line schema: ``{"id": <uuid4 hex>, "recipe": recipe_name,
    "config_hash": config_hash, "sharpe": float, "created": created}``.
    *created* is an ISO string supplied by the caller (injectable for tests).
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "id": uuid.uuid4().hex,
        "recipe": recipe_name,
        "config_hash": config_hash,
        "sharpe": float(sharpe),
        "created": created,
    }
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record) + "\n")


def cumulative_sr_trials(path: Path) -> list[float]:
    """Return per-trial Sharpe values from *path*, de-duplicated on ``config_hash``.

    De-duplication: last occurrence wins (later registrations supersede earlier
    ones with the same hash).  Order is stable by first-seen ``config_hash``.
    Missing or empty file returns ``[]``.
    """
    path = Path(path)
    if not path.exists():
        return []

    # first_seen preserves insertion order; values are updated on each repeat
    first_seen: dict[str, int] = {}  # config_hash -> index in order list
    order: list[str] = []
    last_sharpe: dict[str, float] = {}

    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        obj = json.loads(line)
        h = obj["config_hash"]
        if h not in first_seen:
            first_seen[h] = len(order)
            order.append(h)
        last_sharpe[h] = float(obj["sharpe"])

    return [last_sharpe[h] for h in order]
