"""Versioned snapshots: Parquet plus a JSON sidecar, written only on change.

Layout produced here:

    raw/<feed>/<YYYY-MM-DD>/<original filename>     (only when <= 2 MB)
    data/<feed>/<version-id>/data.parquet
    data/<feed>/<version-id>/meta.json

The version id is `<date>-<sha256[:8]>`, where <date> is the Last-Modified
date when the publisher sends one and the fetch date otherwise.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path

import pandas as pd

from govdiff.config import RAW_KEEP_MAX_BYTES, repo_root


@dataclass
class SnapshotResult:
    version_id: str
    created: bool
    path: Path
    row_count: int
    raw_path: Path | None
    reason: str


def _date_part(last_modified: str | None, fetched_at: str | None) -> str:
    """Prefer the publisher's own date; fall back to when we fetched."""
    if last_modified:
        try:
            return parsedate_to_datetime(last_modified).date().isoformat()
        except (TypeError, ValueError):
            # Callers may hand us a plain ISO date (e.g. a listing publication
            # date) instead of an HTTP-date - accept that form too.
            candidate = last_modified.strip()[:10]
            try:
                return datetime.fromisoformat(candidate).date().isoformat()
            except ValueError:
                pass
    if fetched_at:
        try:
            return datetime.fromisoformat(fetched_at.replace("Z", "+00:00")).date().isoformat()
        except ValueError:
            pass
    return datetime.now(timezone.utc).date().isoformat()


def version_id(sha256: str, last_modified: str | None = None, fetched_at: str | None = None) -> str:
    return "%s-%s" % (_date_part(last_modified, fetched_at), sha256[:8])


def feed_dir(feed_id: str, root: Path | None = None) -> Path:
    return (root or repo_root()) / "data" / feed_id


def list_versions(feed_id: str, root: Path | None = None) -> list[str]:
    """Version ids on disk, oldest first (the id sorts date-then-hash)."""
    directory = feed_dir(feed_id, root)
    if not directory.exists():
        return []
    return sorted(p.name for p in directory.iterdir() if p.is_dir() and (p / "meta.json").exists())


def read_meta(feed_id: str, version: str, root: Path | None = None) -> dict:
    with open(feed_dir(feed_id, root) / version / "meta.json", "r", encoding="utf-8") as fh:
        return json.load(fh)


def read_version(feed_id: str, version: str, root: Path | None = None) -> pd.DataFrame:
    return pd.read_parquet(feed_dir(feed_id, root) / version / "data.parquet")


def find_version_by_sha(feed_id: str, sha256: str, root: Path | None = None) -> str | None:
    for version in list_versions(feed_id, root):
        if read_meta(feed_id, version, root).get("sha256") == sha256:
            return version
    return None


def store_raw(
    feed_id: str,
    content: bytes,
    filename: str,
    date_part: str,
    root: Path | None = None,
) -> Path | None:
    """Keep the untouched source file when it is small enough to commit."""
    if len(content) > RAW_KEEP_MAX_BYTES:
        return None
    target_dir = (root or repo_root()) / "raw" / feed_id / date_part
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / filename
    target.write_bytes(content)
    return target


def write_snapshot(
    feed_id: str,
    frame: pd.DataFrame,
    *,
    source_url: str,
    sha256: str,
    fetched_at: str,
    last_modified: str | None = None,
    key_fields: list[str] | None = None,
    extra: dict | None = None,
    root: Path | None = None,
) -> SnapshotResult:
    """Write a new version, or report the existing one when nothing changed.

    Idempotence has two arms: the same content hash never produces a second
    version directory, and re-running against an existing version directory
    rewrites nothing.
    """
    root = root or repo_root()
    existing = find_version_by_sha(feed_id, sha256, root)
    if existing:
        return SnapshotResult(
            version_id=existing,
            created=False,
            path=feed_dir(feed_id, root) / existing,
            row_count=int(read_meta(feed_id, existing, root).get("row_count", 0)),
            raw_path=None,
            reason="sha256 already snapshotted",
        )

    vid = version_id(sha256, last_modified, fetched_at)
    target_dir = feed_dir(feed_id, root) / vid
    target_dir.mkdir(parents=True, exist_ok=True)

    parquet_path = target_dir / "data.parquet"
    frame.to_parquet(parquet_path, engine="pyarrow", index=False)

    meta = {
        "feed": feed_id,
        "version_id": vid,
        "schema": [{"name": str(c), "dtype": str(frame[c].dtype)} for c in frame.columns],
        "key_fields": list(key_fields or []),
        "source_url": source_url,
        "fetched_at": fetched_at,
        "last_modified": last_modified,
        "sha256": sha256,
        "row_count": int(len(frame)),
    }
    if extra:
        meta.update(extra)
    with open(target_dir / "meta.json", "w", encoding="utf-8", newline="\n") as fh:
        json.dump(meta, fh, indent=2, ensure_ascii=False, sort_keys=True)
        fh.write("\n")

    return SnapshotResult(
        version_id=vid,
        created=True,
        path=target_dir,
        row_count=int(len(frame)),
        raw_path=None,
        reason="new content hash",
    )
