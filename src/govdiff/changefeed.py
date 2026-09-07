"""The change feed: `docs/feed.xml`, `docs/<feed>/feed.xml` and `CHANGES.md`.

Same walk, same discipline and the same command as `docs/index.json`: one
`govdiff index` writes all of it, so the nightly job has one step and one
commit for everything derived from the archive.

**An Atom feed is the one format a finance or compliance team can subscribe to
without writing a line of code.** Every entry is one diff: the counts in the
title, a plain-text summary of what moved, a link straight into the viewer's
deep link for that diff, and an enclosure pointing at the raw JSONL for anyone
who would rather parse it.

Two rules make the output safe to commit every night:

**`updated` is the newest diff's own `generated_at`, never `now()`.** A feed
whose timestamp moved every night would be a new file every night, a commit
every night, and - worse - a "something changed" signal in every subscriber's
reader on a night when nothing changed. Every timestamp in here comes from a
`.summary.json` on disk.

**Everything is sorted.** Entries by date then id, columns by count then name,
feeds by id. Running the command twice on an unchanged archive produces
byte-identical files, which is what the tests assert.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from govdiff.config import repo_root
from govdiff.index import _read_json, build_index

# Where the viewer is published. Deep links are built against it.
SITE_URL = "https://phillipmex.github.io/latam-gov-diffs/"

# RFC 4151 tag URI parts. The date is a constant on purpose: an entry id has to
# stay identical for the life of the entry, so it cannot carry a build date.
TAG_AUTHORITY = "phillipmex.github.io"
TAG_DATE = "2026"
TAG_PREFIX = "tag:%s,%s:latam-gov-diffs" % (TAG_AUTHORITY, TAG_DATE)

# Relative to the repository root.
DEFAULT_ATOM_PATH = "docs/feed.xml"
DEFAULT_CHANGES_PATH = "CHANGES.md"

# How many columns the Atom summary and the CHANGES.md table name.
ATOM_TOP_FIELDS = 5
CHANGES_TOP_FIELDS = 3

# Only used when the archive holds no diff and no version at all, which is the
# state of a fresh clone before the first harvest.
EMPTY_ARCHIVE_UPDATED = "2026-09-07T00:00:00+00:00"

_ESCAPES = (("&", "&amp;"), ("<", "&lt;"), (">", "&gt;"), ('"', "&quot;"))


def _esc(value) -> str:
    out = "" if value is None else str(value)
    for needle, replacement in _ESCAPES:
        out = out.replace(needle, replacement)
    return out


def _iso(value: str | None) -> str | None:
    """A timestamp we can sort on, or None when it is not parseable."""
    if not value:
        return None
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return value


def _sort_key(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _top_fields(changed_fields: dict, limit: int) -> list[tuple[str, int]]:
    """Columns that moved, most first, ties broken by name so it is stable."""
    entries = [(name, int(count)) for name, count in (changed_fields or {}).items()]
    entries.sort(key=lambda pair: (-pair[1], pair[0]))
    return entries[:limit]


def _bytes_label(value) -> str:
    if not value:
        return ""
    value = int(value)
    if value < 1024:
        return "%d B" % value
    if value < 1024 * 1024:
        return "%.0f kB" % (value / 1024)
    return "%.1f MB" % (value / (1024 * 1024))


def build_entries(root: Path | None = None, index: dict | None = None) -> list[dict]:
    """One entry per diff in the archive, newest first.

    Reads the `.summary.json` files for the two things `index.json` does not
    carry: each diff's own `generated_at`, which is the entry timestamp, and
    its `changed_fields` histogram, which is what makes the summary readable.
    """
    root = (root or repo_root()).resolve()
    index = index or build_index(root)
    entries: list[dict] = []
    for feed in index["feeds"]:
        for diff in feed["diffs"]:
            summary = {}
            if diff.get("summary"):
                path = root / diff["summary"]
                if path.exists():
                    summary = _read_json(path)
            generated = _iso(summary.get("generated_at")) or (
                "%sT00:00:00+00:00" % (diff.get("to") or "")[:10]
            )
            entries.append(
                {
                    "feed": feed["id"],
                    "feed_title": feed["title"],
                    "publisher": feed["publisher"],
                    "country": feed["country"],
                    "from": diff["from"],
                    "to": diff["to"],
                    "from_date": (diff["from"] or "")[:10],
                    "to_date": (diff["to"] or "")[:10],
                    "added": diff["added"],
                    "changed": diff["changed"],
                    "removed": diff["removed"],
                    "unchanged": diff["unchanged"],
                    "rows_from": diff["rows_from"],
                    "rows_to": diff["rows_to"],
                    "jsonl": diff["jsonl"],
                    "jsonl_bytes": diff["jsonl_bytes"],
                    "summary_path": diff["summary"],
                    "format": diff.get("format"),
                    "generated_at": generated,
                    "changed_fields": summary.get("changed_fields") or {},
                    "fields_added": list(summary.get("fields_added") or []),
                    "fields_removed": list(summary.get("fields_removed") or []),
                }
            )
    # Newest first. The version id carries the date, so sorting on it sorts by
    # date; feed and from-version break the ties deterministically.
    entries.sort(key=lambda e: (e["to"] or "", e["from"] or "", e["feed"]), reverse=True)
    return entries


def entry_id(entry: dict) -> str:
    """A tag URI that never changes for this diff, on any host or mirror."""
    return "%s/%s/%s__%s" % (TAG_PREFIX, entry["feed"], entry["from"], entry["to"])


def entry_title(entry: dict) -> str:
    return "%s %s → %s: +%s / ~%s / −%s" % (
        entry["feed"],
        entry["from_date"],
        entry["to_date"],
        entry["added"],
        entry["changed"],
        entry["removed"],
    )


def viewer_link(entry: dict) -> str:
    return "%s#feed=%s&from=%s&to=%s" % (SITE_URL, entry["feed"], entry["from"], entry["to"])


def raw_link(entry: dict, raw_base: str) -> str | None:
    if not entry["jsonl"]:
        return None
    return raw_base + entry["jsonl"]


def entry_summary_text(entry: dict) -> str:
    """The plain-text body of one Atom entry."""
    lines = [
        "%s added, %s changed, %s removed, %s unchanged."
        % (entry["added"], entry["changed"], entry["removed"], entry["unchanged"]),
        "The table went from %s rows to %s." % (entry["rows_from"], entry["rows_to"]),
    ]
    top = _top_fields(entry["changed_fields"], ATOM_TOP_FIELDS)
    if top:
        named = ", ".join("%s (%s)" % (name, count) for name, count in top)
        total = len(entry["changed_fields"])
        if total > len(top):
            named += ", and %d more column(s)" % (total - len(top))
        lines.append("Columns that moved: %s." % named)
    if entry["fields_added"]:
        lines.append("Columns the publisher added: %s." % ", ".join(entry["fields_added"]))
    if entry["fields_removed"]:
        lines.append(
            "Columns the publisher dropped: %s. A dropped column makes every row that"
            " filled it read as changed." % ", ".join(entry["fields_removed"])
        )
    if entry["jsonl"]:
        size = _bytes_label(entry["jsonl_bytes"])
        lines.append("Diff file: %s%s." % (entry["jsonl"], " (%s)" % size if size else ""))
    lines.append("Source: %s, %s." % (entry["publisher"], entry["country"]))
    return "\n".join(lines)


def _feed_updated(entries: list[dict], index: dict, feed_id: str | None) -> str:
    """The feed's `updated`: the newest entry's own timestamp, never now().

    A feed with no diff yet - `sat69b` is one, and will be until SAT
    republishes - falls back to the date of its newest archived version at
    midnight UTC. It is a fact about the archive rather than about this run,
    which is the whole point: the file has to be byte-stable.
    """
    if entries:
        return max(entries, key=lambda e: _sort_key(e["generated_at"]))["generated_at"]
    dates = []
    for feed in index["feeds"]:
        if feed_id and feed["id"] != feed_id:
            continue
        for version in feed["versions"]:
            dates.append(version["date"])
    if dates:
        return "%sT00:00:00+00:00" % max(dates)
    return EMPTY_ARCHIVE_UPDATED


def render_atom(index: dict, entries: list[dict], feed_id: str | None = None) -> str:
    """Atom 1.0 for the whole archive, or for one feed when `feed_id` is given."""
    raw_base = index["raw_base_url"]
    if feed_id:
        selected = [e for e in entries if e["feed"] == feed_id]
        meta = next((f for f in index["feeds"] if f["id"] == feed_id), None)
        title = "latam-gov-diffs: %s" % feed_id
        subtitle = "%s - %s, %s" % (
            (meta or {}).get("title", feed_id),
            (meta or {}).get("publisher", ""),
            (meta or {}).get("country", ""),
        )
        self_href = "%s%s/feed.xml" % (SITE_URL, feed_id)
        alternate = "%s#feed=%s" % (SITE_URL, feed_id)
        this_id = "%s/%s" % (TAG_PREFIX, feed_id)
    else:
        selected = entries
        title = "latam-gov-diffs: every change"
        subtitle = (
            "Record-level diffs of Latin American government reference data, one entry per"
            " published revision."
        )
        self_href = "%sfeed.xml" % SITE_URL
        alternate = SITE_URL
        this_id = TAG_PREFIX

    out = ['<?xml version="1.0" encoding="utf-8"?>']
    out.append('<feed xmlns="http://www.w3.org/2005/Atom">')
    out.append("  <title>%s</title>" % _esc(title))
    out.append("  <subtitle>%s</subtitle>" % _esc(subtitle))
    out.append("  <id>%s</id>" % _esc(this_id))
    out.append("  <updated>%s</updated>" % _esc(_feed_updated(selected, index, feed_id)))
    out.append('  <link rel="self" type="application/atom+xml" href="%s"/>' % _esc(self_href))
    out.append('  <link rel="alternate" type="text/html" href="%s"/>' % _esc(alternate))
    out.append("  <author><name>latam-gov-diffs maintainers</name></author>")
    out.append("  <rights>Code MIT. Archived data is public government data.</rights>")
    # No version number in the generator: `govdiff --version` differs between a
    # clone and a wheel, and this file has to be byte-identical from either.
    out.append('  <generator uri="%s">govdiff index</generator>' % _esc(index["repository"]))
    for entry in selected:
        out.append("  <entry>")
        out.append("    <id>%s</id>" % _esc(entry_id(entry)))
        out.append("    <title>%s</title>" % _esc(entry_title(entry)))
        out.append("    <updated>%s</updated>" % _esc(entry["generated_at"]))
        out.append(
            '    <link rel="alternate" type="text/html" href="%s"/>' % _esc(viewer_link(entry))
        )
        raw = raw_link(entry, raw_base)
        if raw:
            out.append(
                '    <link rel="enclosure" type="application/x-ndjson" length="%d" href="%s"/>'
                % (int(entry["jsonl_bytes"] or 0), _esc(raw))
            )
        out.append('    <category term="%s"/>' % _esc(entry["feed"]))
        out.append('    <content type="text">%s</content>' % _esc(entry_summary_text(entry)))
        out.append("  </entry>")
    out.append("</feed>")
    return "\n".join(out) + "\n"


def _md_cell(value: str) -> str:
    return str(value).replace("|", "\\|")


def render_changes(index: dict, entries: list[dict]) -> str:
    """`CHANGES.md`: the same information as the Atom feed, for a human."""
    versions = sum(f["version_count"] for f in index["feeds"])
    diffs = sum(f["diff_count"] for f in index["feeds"])
    out = [
        "# Changes",
        "",
        "Every revision this archive has recorded, newest first, one section per feed.",
        "",
        "**Generated by `govdiff index`** from the `.summary.json` files under `diffs/`."
        " Do not edit by hand - the next nightly run overwrites it. The same command writes"
        " `docs/index.json`, the Atom feed `docs/feed.xml` and the per-feed Atom feeds"
        " `docs/<feed>/feed.xml`.",
        "",
        "%d feed(s), %s archived version(s), %s recorded change(s)."
        % (index["feed_count"], f"{versions:,}", f"{diffs:,}"),
        "",
    ]
    for feed in index["feeds"]:
        mine = [e for e in entries if e["feed"] == feed["id"]]
        out.append("## %s" % feed["id"])
        out.append("")
        out.append("%s - %s, %s." % (feed["title"], feed["publisher"], feed["country"]))
        line = "Keyed by %s. %d archived version(s)" % (
            ", ".join("`%s`" % k for k in feed["key_fields"]) or "(no key)",
            feed["version_count"],
        )
        if feed["versions"]:
            line += " (%s to %s)" % (feed["versions"][0]["date"], feed["versions"][-1]["date"])
        line += ", %d recorded change(s)." % feed["diff_count"]
        out.append(line)
        links = []
        if feed.get("document_url"):
            links.append("[source document](%s)" % feed["document_url"])
        links.append("[Atom feed](docs/%s/feed.xml)" % feed["id"])
        out.append(" - ".join(links))
        out.append("")
        if not mine:
            out.append(
                "No change recorded yet. A diff needs two archived versions; the first"
                " revision the publisher issues will appear here."
            )
            out.append("")
            continue
        out.append(
            "| published | change | added | changed | removed | columns that moved most | diff |"
        )
        out.append("|---|---|--:|--:|--:|---|---|")
        for entry in mine:
            top = _top_fields(entry["changed_fields"], CHANGES_TOP_FIELDS)
            fields = ", ".join("`%s` (%s)" % (name, count) for name, count in top) or "-"
            total = len(entry["changed_fields"])
            if total > len(top):
                fields += ", +%d more" % (total - len(top))
            diff_cell = (
                "[jsonl](%s)" % entry["jsonl"] if entry["jsonl"] else "(file missing)"
            )
            out.append(
                "| %s | `%s` → `%s` | %s | %s | %s | %s | %s |"
                % (
                    entry["to_date"],
                    _md_cell(entry["from"]),
                    _md_cell(entry["to"]),
                    f"{entry['added']:,}",
                    f"{entry['changed']:,}",
                    f"{entry['removed']:,}",
                    _md_cell(fields),
                    diff_cell,
                )
            )
        out.append("")
    return "\n".join(out).rstrip("\n") + "\n"


def _write_if_changed(target: Path, body: str) -> bool:
    """Write only on a real difference, so an unchanged night touches nothing."""
    encoded = body.encode("utf-8")
    if target.exists():
        try:
            if target.read_bytes() == encoded:
                return False
        except OSError:  # pragma: no cover - unreadable target
            pass
    target.parent.mkdir(parents=True, exist_ok=True)
    with open(target, "wb") as fh:
        fh.write(encoded)
    return True


def write_change_feed(root: Path | None = None, index: dict | None = None) -> dict:
    """Write `docs/feed.xml`, `docs/<feed>/feed.xml` and `CHANGES.md`.

    Returns a report: which files were rewritten and how many entries the feed
    carries.
    """
    root = (root or repo_root()).resolve()
    index = index or build_index(root)
    entries = build_entries(root, index)

    written: list[str] = []
    unchanged: list[str] = []

    def record(path: Path, body: str) -> None:
        (written if _write_if_changed(path, body) else unchanged).append(
            path.resolve().relative_to(root).as_posix()
        )

    record(root / DEFAULT_ATOM_PATH, render_atom(index, entries))
    for feed in index["feeds"]:
        record(
            root / "docs" / feed["id"] / "feed.xml",
            render_atom(index, entries, feed_id=feed["id"]),
        )
    record(root / DEFAULT_CHANGES_PATH, render_changes(index, entries))

    return {
        "entries": len(entries),
        "written": written,
        "unchanged": unchanged,
        "updated": _feed_updated(entries, index, None),
    }
