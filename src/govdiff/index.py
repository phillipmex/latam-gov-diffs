"""The machine-readable archive index written to `docs/index.json`.

One JSON document describing everything the archive holds: every feed from
`feeds.yaml`, every stored version under `data/`, and every diff under
`diffs/`. It is the contract the npm client and the static viewer both read,
and the only file either of them needs before it knows what exists.

Two rules make it usable as a committed artefact:

**Every path is repo-root relative** (`data/...`, `diffs/...`), never relative
to `docs/`. A reader joins them onto a base URL: the raw.githubusercontent.com
tree for the published archive, or `../` for a local server started at the repo
root. GitHub Pages serves `docs/` as the site root and does not serve `diffs/`
at all, so a docs-relative path would be unresolvable exactly where the viewer
lives.

**Nothing that moves on its own goes in the file.** `generated_at` is the only
timestamp, and the writer keeps the previous file untouched when everything
except `generated_at` is identical. So `.state`'s `last_fetched_at` and
`last_result` are deliberately left out - they change on every nightly run
whether or not the archive changed, and including them would produce a commit
every single night that said nothing.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from govdiff.config import load_feeds, repo_root
from govdiff.snapshot import feed_dir, list_versions, read_meta

# Bumped when the shape of index.json changes.
INDEX_FORMAT = 1

# Relative to the repository root.
DEFAULT_INDEX_PATH = "docs/index.json"


def _rel(path: Path, root: Path) -> str:
    """A repo-root relative path with forward slashes, on any OS."""
    return path.resolve().relative_to(root.resolve()).as_posix()


def _read_json(path: Path) -> dict:
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def _versions_for(feed_id: str, root: Path) -> list[dict]:
    out = []
    for version in list_versions(feed_id, root):
        directory = feed_dir(feed_id, root) / version
        meta = read_meta(feed_id, version, root)
        parquet = directory / "data.parquet"
        entry = {
            "version_id": version,
            # The version id is `<date>-<sha256[:8]>`, so the date is free.
            "date": version[:10],
            "row_count": int(meta.get("row_count") or 0),
            "column_count": len(meta.get("schema") or []),
            "sha256": meta.get("sha256"),
            "source_url": meta.get("source_url"),
            "parquet": _rel(parquet, root) if parquet.exists() else None,
            "parquet_bytes": parquet.stat().st_size if parquet.exists() else None,
            "meta": _rel(directory / "meta.json", root),
        }
        published = meta.get("published")
        if published:
            entry["published"] = published
        out.append(entry)
    return out


def _diffs_for(feed_id: str, root: Path) -> list[dict]:
    directory = root / "diffs" / feed_id
    if not directory.exists():
        return []
    out = []
    for summary_path in sorted(directory.glob("*.summary.json")):
        summary = _read_json(summary_path)
        jsonl = summary_path.with_name(summary_path.name[: -len(".summary.json")] + ".jsonl")
        out.append(
            {
                "from": summary.get("from_version"),
                "to": summary.get("to_version"),
                "jsonl": _rel(jsonl, root) if jsonl.exists() else None,
                "jsonl_bytes": jsonl.stat().st_size if jsonl.exists() else None,
                "summary": _rel(summary_path, root),
                "format": summary.get("format"),
                "added": int(summary.get("added") or 0),
                "changed": int(summary.get("changed") or 0),
                "removed": int(summary.get("removed") or 0),
                "unchanged": int(summary.get("unchanged") or 0),
                "rows_from": int(summary.get("rows_from") or 0),
                "rows_to": int(summary.get("rows_to") or 0),
            }
        )
    # Chain order, not filename order: a diff sorts after the diff it follows.
    out.sort(key=lambda d: ((d["from"] or ""), (d["to"] or "")))
    return out


def _state_for(feed_id: str, root: Path) -> dict | None:
    path = root / ".state" / ("%s.json" % feed_id)
    if not path.exists():
        return None
    state = _read_json(path)
    # Only the fields that describe the archive. See the module docstring for
    # why last_fetched_at and last_result are not here.
    return {
        "version_id": state.get("version_id"),
        "sha256": state.get("sha256"),
        "last_modified": state.get("last_modified"),
        "row_count": state.get("row_count"),
    }


def build_index(root: Path | None = None, generated_at: str | None = None) -> dict:
    """The whole archive as one dictionary. Reads no network and no Parquet."""
    root = (root or repo_root()).resolve()
    feeds = load_feeds(root / "feeds.yaml")
    entries = []
    for feed_id in sorted(feeds):
        feed = feeds[feed_id]
        versions = _versions_for(feed_id, root)
        diffs = _diffs_for(feed_id, root)
        entries.append(
            {
                "id": feed.id,
                "title": feed.name,
                "country": feed.country,
                "publisher": feed.publisher,
                "enabled": feed.enabled,
                "format": feed.format,
                "document_url": feed.document_url,
                "listing_url": feed.listing_url,
                "key_fields": list(feed.key_fields),
                "version_count": len(versions),
                "diff_count": len(diffs),
                "latest_version": versions[-1]["version_id"] if versions else None,
                "state": _state_for(feed_id, root),
                "versions": versions,
                "diffs": diffs,
            }
        )
    return {
        "format": INDEX_FORMAT,
        "generated_at": generated_at
        or datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "repository": "https://github.com/phillipmex/latam-gov-diffs",
        "raw_base_url": "https://raw.githubusercontent.com/phillipmex/latam-gov-diffs/main/",
        "path_base": "repository-root",
        "feed_count": len(entries),
        "feeds": entries,
    }


def render_index(index: dict) -> str:
    """Deterministic bytes: sorted keys, two-space indent, trailing newline."""
    return json.dumps(index, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def _same_except_timestamp(a: dict, b: dict) -> bool:
    left = {k: v for k, v in a.items() if k != "generated_at"}
    right = {k: v for k, v in b.items() if k != "generated_at"}
    return left == right


def write_index(root: Path | None = None, output: Path | None = None) -> dict:
    """Write `docs/index.json`, but only when the archive actually moved.

    Returns a small report: the path, whether it was rewritten, and the totals.
    """
    root = (root or repo_root()).resolve()
    target = Path(output) if output else (root / DEFAULT_INDEX_PATH)
    index = build_index(root)

    changed = True
    if target.exists():
        try:
            previous = _read_json(target)
        except (ValueError, OSError):
            previous = None
        if previous is not None and _same_except_timestamp(previous, index):
            changed = False
            index = previous

    if changed:
        target.parent.mkdir(parents=True, exist_ok=True)
        with open(target, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(render_index(index))

    return {
        "path": target,
        "changed": changed,
        "feeds": index["feed_count"],
        "versions": sum(f["version_count"] for f in index["feeds"]),
        "diffs": sum(f["diff_count"] for f in index["feeds"]),
        "generated_at": index["generated_at"],
    }
