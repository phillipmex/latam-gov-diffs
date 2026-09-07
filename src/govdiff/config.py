"""Repository layout, the feed registry, and parser loading."""

from __future__ import annotations

import importlib
import os
from dataclasses import dataclass, field
from pathlib import Path
from types import ModuleType

import yaml

from govdiff.errors import FeedError

# Raw files at or below this size are kept under raw/ for provenance.
# Anything larger is hashed, parsed in memory, and discarded.
RAW_KEEP_MAX_BYTES = 2 * 1024 * 1024

# Absolute ceiling on a single response. Well above the 46.5 MB SAT catalogue,
# low enough that a runaway response cannot fill the disk.
FETCH_MAX_BYTES = 128 * 1024 * 1024


def repo_root() -> Path:
    """Directory holding feeds.yaml, data/, diffs/, raw/ and .state/."""
    override = os.environ.get("GOVDIFF_ROOT")
    if override:
        return Path(override).resolve()
    # src/govdiff/config.py -> src/govdiff -> src -> repo root
    return Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class Feed:
    id: str
    name: str
    country: str
    publisher: str
    enabled: bool
    listing_url: str | None
    document_url: str | None
    format: str
    parser: str | None
    key_fields: list[str] = field(default_factory=list)
    notes: str = ""

    def load_parser(self) -> ModuleType:
        if not self.parser:
            raise FeedError(f"feed '{self.id}' has no parser configured")
        return importlib.import_module(self.parser)


def _feed_from_mapping(raw: dict) -> Feed:
    missing = [k for k in ("id", "name", "country", "publisher", "format") if not raw.get(k)]
    if missing:
        raise FeedError(f"feed entry is missing required keys: {', '.join(missing)}")
    return Feed(
        id=raw["id"],
        name=raw["name"],
        country=raw["country"],
        publisher=raw["publisher"],
        enabled=bool(raw.get("enabled", False)),
        listing_url=raw.get("listing_url"),
        document_url=raw.get("document_url"),
        format=raw["format"],
        parser=raw.get("parser"),
        key_fields=list(raw.get("key_fields") or []),
        notes=(raw.get("notes") or "").strip(),
    )


def load_feeds(path: Path | None = None) -> dict[str, Feed]:
    path = path or (repo_root() / "feeds.yaml")
    with open(path, "r", encoding="utf-8") as fh:
        doc = yaml.safe_load(fh) or {}
    entries = doc.get("feeds") or []
    feeds: dict[str, Feed] = {}
    for entry in entries:
        feed = _feed_from_mapping(entry)
        if feed.id in feeds:
            raise FeedError(f"duplicate feed id in registry: {feed.id}")
        feeds[feed.id] = feed
    return feeds


def get_feed(feed_id: str, path: Path | None = None) -> Feed:
    feeds = load_feeds(path)
    if feed_id not in feeds:
        raise FeedError(f"unknown feed '{feed_id}' (known: {', '.join(sorted(feeds))})")
    return feeds[feed_id]
