"""Repository layout, the feed registry, and parser loading."""

from __future__ import annotations

import importlib
import os
from dataclasses import dataclass, field
from pathlib import Path
from types import ModuleType

import yaml

from govdiff.errors import FeedError, RepoNotFound

# Raw files at or below this size are kept under raw/ for provenance.
# Anything larger is hashed, parsed in memory, and discarded.
RAW_KEEP_MAX_BYTES = 2 * 1024 * 1024

# Absolute ceiling on a single response. Well above the 46.5 MB SAT catalogue,
# low enough that a runaway response cannot fill the disk.
FETCH_MAX_BYTES = 128 * 1024 * 1024


# The one file that proves a directory is an archive checkout.
ARCHIVE_MARKER = "feeds.yaml"

ARCHIVE_CLONE_URL = "https://github.com/phillipmex/latam-gov-diffs"

_NO_ARCHIVE = (
    "no archive found.\n"
    "govdiff reads and writes a checkout of the latam-gov-diffs archive - the directory\n"
    "holding %s, data/, diffs/ and .state/. The package on PyPI is the tool only; it does\n"
    "not carry the archive with it.\n"
    "\n"
    "Do one of these:\n"
    "  1. clone the archive and run the command inside it:\n"
    "       git clone %s\n"
    "       cd latam-gov-diffs\n"
    "  2. point at an existing checkout:  govdiff --repo /path/to/latam-gov-diffs <command>\n"
    "  3. or set it once:                 GOVDIFF_REPO=/path/to/latam-gov-diffs\n"
    "\n"
    "Looked at: %s"
) % (ARCHIVE_MARKER, ARCHIVE_CLONE_URL, "%s")


def repo_root() -> Path:
    """Directory holding feeds.yaml, data/, diffs/, raw/ and .state/.

    This is the *source tree* answer and is right only when govdiff is running
    out of a clone (including `pip install -e .`). In a wheel install it points
    into site-packages, which is why every entry point goes through
    `resolve_repo_root()` first. Kept unchanged so library callers that already
    depend on it are not moved out from under.
    """
    override = os.environ.get("GOVDIFF_ROOT")
    if override:
        return Path(override).resolve()
    # src/govdiff/config.py -> src/govdiff -> src -> repo root
    return Path(__file__).resolve().parents[2]


def is_archive_root(path: Path) -> bool:
    """True when `path` looks like an archive checkout (it holds feeds.yaml)."""
    try:
        return (Path(path) / ARCHIVE_MARKER).is_file()
    except OSError:  # pragma: no cover - unreadable path
        return False


def resolve_repo_root(explicit: str | Path | None = None) -> Path:
    """Where the archive lives, resolved in one fixed order.

    1. `--repo PATH` on the command line (this argument).
    2. the `GOVDIFF_REPO` environment variable.
    3. the current working directory, when it holds `feeds.yaml`.
    4. otherwise: a clear error telling the reader to clone the archive or
       pass `--repo`.

    The package-relative guess `repo_root()` is deliberately *not* in this
    chain. It is correct in a clone and silently wrong in a wheel install -
    it resolves into site-packages, where there is no archive - and a tool
    that quietly writes an archive into site-packages is worse than one that
    says it cannot find it.

    `GOVDIFF_ROOT` is still honoured as an alias for `GOVDIFF_REPO`, because
    days 1-4 documented it and something may already be set to it.
    """
    tried: list[str] = []

    if explicit:
        candidate = Path(explicit).expanduser().resolve()
        if is_archive_root(candidate):
            return candidate
        raise RepoNotFound(
            "--repo %s does not hold %s, so it is not an archive checkout."
            % (candidate, ARCHIVE_MARKER)
        )

    for name in ("GOVDIFF_REPO", "GOVDIFF_ROOT"):
        value = os.environ.get(name)
        if not value:
            continue
        candidate = Path(value).expanduser().resolve()
        if is_archive_root(candidate):
            return candidate
        raise RepoNotFound(
            "%s is set to %s, which does not hold %s." % (name, candidate, ARCHIVE_MARKER)
        )

    cwd = Path.cwd().resolve()
    if is_archive_root(cwd):
        return cwd
    tried.append(str(cwd))

    raise RepoNotFound(_NO_ARCHIVE % ", ".join(tried))


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
