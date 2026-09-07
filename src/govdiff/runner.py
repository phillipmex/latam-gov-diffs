"""The two things this project actually does: a nightly run, and a bootstrap."""

from __future__ import annotations

import time
from pathlib import Path

import requests

from govdiff.config import Feed, get_feed, load_feeds, repo_root
from govdiff.diff import diff_versions
from govdiff.errors import FeedError, SourceChallenged
from govdiff.fetch import (
    fetch,
    filename_from_disposition,
    load_state,
    make_session,
    save_state,
    utc_now_iso,
)
from govdiff.snapshot import (
    find_version_by_sha,
    list_versions,
    read_meta,
    store_raw,
    write_snapshot,
)

# Gap between requests when walking a publisher's back catalogue.
BOOTSTRAP_DELAY_SECONDS = 3

_EXTENSIONS = {"xlsx": ".xlsx", "xls": ".xls", "csv": ".csv"}


def _raw_filename(feed: Feed, disposition: str | None, version_date: str) -> str:
    fallback = "%s-%s%s" % (feed.id, version_date, _EXTENSIONS.get(feed.format, ".bin"))
    return filename_from_disposition(disposition, fallback)


def _previous_version(feed_id: str, version: str, root: Path) -> str | None:
    """The version stored immediately before `version` (ids sort by date)."""
    versions = list_versions(feed_id, root)
    if version not in versions:
        return None
    position = versions.index(version)
    return versions[position - 1] if position > 0 else None


def _ingest(
    feed: Feed,
    content: bytes,
    *,
    source_url: str,
    sha256: str,
    fetched_at: str,
    last_modified: str | None,
    content_disposition: str | None,
    root: Path,
    extra: dict | None = None,
) -> dict:
    """Parse, store raw when small enough, snapshot, and diff against the previous."""
    module = feed.load_parser()
    frame = module.parse(content)

    from govdiff.snapshot import version_id as make_version_id

    vid = make_version_id(sha256, last_modified, fetched_at)
    raw_path = store_raw(feed.id, content, _raw_filename(feed, content_disposition, vid[:10]), vid[:10], root)

    snap = write_snapshot(
        feed.id,
        frame,
        source_url=source_url,
        sha256=sha256,
        fetched_at=fetched_at,
        last_modified=last_modified,
        key_fields=feed.key_fields,
        extra=extra,
        root=root,
    )

    outcome = {
        "feed": feed.id,
        "version_id": snap.version_id,
        "created": snap.created,
        "row_count": snap.row_count,
        "raw_kept": str(raw_path) if raw_path else None,
        "diff": None,
    }
    if snap.created:
        previous = _previous_version(feed.id, snap.version_id, root)
        if previous:
            outcome["diff"] = diff_versions(feed.id, previous, snap.version_id, feed.key_fields, root)
    return outcome


def run_feed(feed_id: str, root: Path | None = None, session=None) -> dict:
    """Fetch the current document, snapshot it if it changed, diff it."""
    root = root or repo_root()
    feed = get_feed(feed_id, root / "feeds.yaml")
    if not feed.enabled:
        raise FeedError("feed '%s' is disabled in feeds.yaml" % feed_id)
    if not feed.parser:
        raise FeedError("feed '%s' has no parser yet" % feed_id)

    session = session or make_session()
    state = load_state(feed.id, root)
    module = feed.load_parser()

    # A feed whose publisher indexes its releases resolves the newest one from
    # the listing (one listing request per run). Everything else uses the URL
    # pinned in feeds.yaml.
    document_url = feed.document_url
    extra: dict = {}
    if hasattr(module, "current_document"):
        current = module.current_document(session=session)
        document_url = current["url"]
        extra = {"published": current.get("published"), "listing_title": current.get("title")}
    if not document_url:
        raise FeedError("feed '%s' has no document_url to fetch" % feed_id)

    # A parser may declare that its publisher's ETag is not evidence about the
    # bytes; then the conditional request asks on Last-Modified alone and the
    # sha256 of the body settles it. See govdiff.feeds.sat69b.
    try:
        result = fetch(
            document_url,
            state=state,
            session=session,
            use_etag=getattr(module, "USE_ETAG", True),
        )
    except SourceChallenged as exc:
        state.update(
            {
                "feed": feed.id,
                "last_fetched_at": utc_now_iso(),
                "last_result": "challenged",
                "last_error": str(exc),
            }
        )
        save_state(feed.id, state, root)
        raise

    # The version date comes from Last-Modified when the server sends one, and
    # from the publisher's own release date on the listing when it does not.
    # The NF-e portal sends neither ETag nor Last-Modified for documents.
    listed_date = None
    if extra.get("published"):
        day, month, year = extra["published"].split("/")
        listed_date = "%s-%s-%s" % (year, month, day)
    version_date_hint = result.last_modified or listed_date

    if result.not_modified:
        outcome = {"feed": feed.id, "version_id": state.get("version_id"), "created": False,
                   "row_count": state.get("row_count"), "raw_kept": None, "diff": None,
                   "note": "304 Not Modified"}
    elif find_version_by_sha(feed.id, result.sha256, root):
        existing = find_version_by_sha(feed.id, result.sha256, root)
        outcome = {"feed": feed.id, "version_id": existing, "created": False,
                   "row_count": int(read_meta(feed.id, existing, root).get("row_count", 0)),
                   "raw_kept": None, "diff": None, "note": "content hash unchanged"}
    else:
        outcome = _ingest(
            feed,
            result.content,
            source_url=document_url,
            sha256=result.sha256,
            fetched_at=result.fetched_at,
            last_modified=version_date_hint,
            content_disposition=result.content_disposition,
            root=root,
            extra={k: v for k, v in extra.items() if v},
        )

    state.update(
        {
            "feed": feed.id,
            "source_url": document_url,
            "last_fetched_at": result.fetched_at,
            "last_result": "new_version" if outcome["created"] else "unchanged",
            "etag": result.etag,
            "last_modified": result.last_modified,
            "sha256": result.sha256 or state.get("sha256"),
            "version_id": outcome["version_id"],
            "row_count": outcome.get("row_count"),
            "version_count": len(list_versions(feed.id, root)),
            "last_error": None,
        }
    )
    save_state(feed.id, state, root)
    return outcome


def run_all(root: Path | None = None) -> list[dict]:
    root = root or repo_root()
    session = make_session()
    outcomes = []
    for feed in load_feeds(root / "feeds.yaml").values():
        if feed.enabled and feed.parser:
            outcomes.append(run_feed(feed.id, root, session=session))
    return outcomes


def bootstrap_feed(feed_id: str, root: Path | None = None, delay: int = BOOTSTRAP_DELAY_SECONDS) -> dict:
    """Load every release the publisher indexes, then diff consecutive versions.

    Works for any feed whose parser exposes `list_versions()`. A back-version
    URL that has been taken down (404) is recorded and the walk continues; the
    surviving releases still diff against each other.
    """
    root = root or repo_root()
    feed = get_feed(feed_id, root / "feeds.yaml")
    module = feed.load_parser()
    if not hasattr(module, "list_versions"):
        raise FeedError("feed '%s' has no list_versions(), so it cannot be bootstrapped" % feed_id)
    session = make_session()

    entries = module.list_versions(session=session)
    report: dict = {"feed": feed.id, "listed": len(entries), "versions": [], "diffs": [], "missing": []}
    if len(entries) < 2:
        report["note"] = (
            "the listing shows %d %s release(s); a back-catalogue needs "
            "at least 2, so no history was built" % (len(entries), feed.id)
        )
        return report

    ordered_versions: list[str] = []
    for index, entry in enumerate(entries):
        if index:
            time.sleep(delay)
        started = time.monotonic()
        try:
            result = fetch(entry["url"], session=session, conditional=False)
        except requests.HTTPError as exc:
            report["missing"].append(
                {
                    "published": entry["published"],
                    "url": entry["url"],
                    "status": exc.response.status_code if exc.response is not None else None,
                }
            )
            continue
        fetch_seconds = round(time.monotonic() - started, 1)
        outcome = _ingest(
            feed,
            result.content,
            source_url=entry["url"],
            sha256=result.sha256,
            fetched_at=result.fetched_at,
            last_modified=entry["date"],
            content_disposition=result.content_disposition,
            root=root,
            extra={"published": entry["published"], "listing_title": entry["title"]},
        )
        ordered_versions.append(outcome["version_id"])
        report["versions"].append(
            {
                "published": entry["published"],
                "version_id": outcome["version_id"],
                "rows": outcome["row_count"],
                "bytes": result.size,
                "created": outcome["created"],
                "url": entry["url"],
                "fetch_seconds": fetch_seconds,
            }
        )

    if not ordered_versions:
        report["note"] = "every listed release failed to download; nothing was stored"
        return report

    for previous, current in zip(ordered_versions, ordered_versions[1:]):
        report["diffs"].append(diff_versions(feed.id, previous, current, feed.key_fields, root))

    last = report["versions"][-1]
    state = load_state(feed.id, root)
    state.update(
        {
            "feed": feed.id,
            "source_url": last["url"],
            "last_fetched_at": utc_now_iso(),
            "last_result": "bootstrap",
            "etag": None,
            "last_modified": None,
            "sha256": read_meta(feed.id, last["version_id"], root)["sha256"],
            "version_id": last["version_id"],
            "row_count": last["rows"],
            "version_count": len(list_versions(feed.id, root)),
            "last_error": None,
        }
    )
    save_state(feed.id, state, root)
    return report


def rediff_feed(feed_id: str, root: Path | None = None) -> dict:
    """Rebuild every consecutive diff of a feed from the stored Parquet versions.

    No network at all: the snapshots are the record, and a diff is a derived
    file. This is how the archive is migrated when the JSONL record shape
    changes - each pair is written back over the file it replaces, under the
    same `<from>__<to>` name, so the old format leaves no orphan behind.

    A diff file whose two versions are no longer neighbours is reported and
    left alone; nothing is deleted that is not overwritten.
    """
    root = root or repo_root()
    feed = get_feed(feed_id, root / "feeds.yaml")
    if not feed.key_fields:
        raise FeedError("feed '%s' has no key_fields, so it cannot be diffed" % feed_id)

    versions = list_versions(feed.id, root)
    report: dict = {"feed": feed.id, "versions": len(versions), "diffs": [], "orphans": []}
    if len(versions) < 2:
        report["note"] = "%d stored version(s); a diff needs 2" % len(versions)
        return report

    expected = set()
    for previous, current in zip(versions, versions[1:]):
        report["diffs"].append(diff_versions(feed.id, previous, current, feed.key_fields, root))
        expected.add("%s__%s.jsonl" % (previous, current))

    directory = root / "diffs" / feed.id
    if directory.exists():
        report["orphans"] = sorted(
            path.name for path in directory.glob("*.jsonl") if path.name not in expected
        )
    return report


def bootstrap_cclasstrib(root: Path | None = None, delay: int = BOOTSTRAP_DELAY_SECONDS) -> dict:
    """The cClassTrib back catalogue. Kept as a name because day 1 exposed it."""
    return bootstrap_feed("cclasstrib", root, delay)
