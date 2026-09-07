"""Generic record-level differ over two snapshot versions.

Output, per feed pair:

    diffs/<feed>/<from>__<to>.jsonl          one object per changed record
    diffs/<feed>/<from>__<to>.summary.json   counts and schema drift

**Format 2.** A record carries only what changed, and nothing else:

    {"op": "added",   "key": {...}, "after":  {non-null fields of the new row}}
    {"op": "removed", "key": {...}, "before": {non-null fields of the old row}}
    {"op": "changed", "key": {...}, "fields": {"<col>": {"before": ..., "after": ...}}}

Format 1 wrote the whole row on `added`/`removed`, null columns included, and
split a change into parallel `before`/`after` objects. On a wide, sparse feed
that is almost all padding: the catCFDI diff was 20.6 MB for 8,026 records
because a row there is 86 columns of which about 80 are null for any one
catalogue. The counts in `.summary.json` are unaffected - only the payload
shrank - and every summary carries `"format": 2` so a reader can tell which
shape it is looking at.

Columns present on one side only are compared as null on the missing side, so
a publisher adding a column shows up as a change on every row that fills it.
"""

from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from govdiff.config import repo_root
from govdiff.errors import FeedError
from govdiff.snapshot import read_version

# Joins the key-field values into one lookup string. ASCII unit separator, so
# it cannot collide with anything a spreadsheet cell can contain.
_KEY_SEP = "\x1f"

# Bumped when the JSONL record shape changes. 1: whole rows on added/removed,
# parallel before/after objects on changed. 2: only what changed.
DIFF_FORMAT = 2


def _cell(value) -> str | None:
    """Normalise one cell to a string or None, so versions compare cleanly."""
    if value is None:
        return None
    if isinstance(value, float) and pd.isna(value):
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    text = str(value).strip()
    return text or None


def _filled(row: dict) -> dict:
    """Drop the empty columns of a row.

    An `added` or `removed` record is the row itself, and on a feed that puts
    several catalogues in one frame most columns of any given row are null. A
    null here means "this column does not apply to this row", which the reader
    can already see from the columns that are present.
    """
    return {name: value for name, value in row.items() if value is not None}


def _records(frame: pd.DataFrame, key_fields: list[str]) -> tuple[dict, int]:
    """Index rows by their key.

    A key that repeats inside one version gets an occurrence suffix (`#2`,
    `#3`, ...) so duplicates are neither dropped nor silently merged. The
    publisher does ship duplicates: cClassTrib 200003 appears twice in the
    2024-12-07 release.
    """
    missing = [f for f in key_fields if f not in frame.columns]
    if missing:
        raise FeedError("key field(s) not present in snapshot: %s" % ", ".join(missing))

    seen: Counter = Counter()
    indexed: dict[str, dict] = {}
    duplicates = 0
    for row in frame.to_dict(orient="records"):
        clean = {str(k): _cell(v) for k, v in row.items()}
        key_values = tuple(clean.get(f) or "" for f in key_fields)
        seen[key_values] += 1
        occurrence = seen[key_values]
        if occurrence > 1:
            duplicates += 1
            key_id = _KEY_SEP.join(key_values) + "#%d" % occurrence
        else:
            key_id = _KEY_SEP.join(key_values)
        indexed[key_id] = clean
    return indexed, duplicates


def _key_object(key_id: str, key_fields: list[str]) -> dict:
    base, _, occurrence = key_id.partition("#")
    values = base.split(_KEY_SEP)
    obj = {field: values[i] if i < len(values) else None for i, field in enumerate(key_fields)}
    if occurrence:
        obj["_occurrence"] = int(occurrence)
    return obj


def diff_frames(before: pd.DataFrame, after: pd.DataFrame, key_fields: list[str]) -> tuple[list[dict], dict]:
    """Compare two frames; return (records, stats)."""
    if not key_fields:
        raise FeedError("diffing needs at least one key field")

    before_rows, dup_before = _records(before, key_fields)
    after_rows, dup_after = _records(after, key_fields)

    before_cols = [str(c) for c in before.columns]
    after_cols = [str(c) for c in after.columns]
    all_cols = list(dict.fromkeys(before_cols + after_cols))

    records: list[dict] = []
    added = removed = changed = unchanged = 0
    changed_fields: Counter = Counter()

    for key_id in after_rows:
        if key_id not in before_rows:
            added += 1
            records.append(
                {
                    "op": "added",
                    "key": _key_object(key_id, key_fields),
                    "after": _filled(after_rows[key_id]),
                }
            )

    for key_id, old in before_rows.items():
        new = after_rows.get(key_id)
        if new is None:
            removed += 1
            records.append(
                {
                    "op": "removed",
                    "key": _key_object(key_id, key_fields),
                    "before": _filled(old),
                }
            )
            continue
        delta: dict[str, dict] = {}
        for column in all_cols:
            old_value = old.get(column)
            new_value = new.get(column)
            if old_value != new_value:
                delta[column] = {"before": old_value, "after": new_value}
        if delta:
            changed += 1
            changed_fields.update(delta.keys())
            records.append(
                {
                    "op": "changed",
                    "key": _key_object(key_id, key_fields),
                    "fields": delta,
                }
            )
        else:
            unchanged += 1

    # Stable, reviewable ordering: op then key.
    order = {"added": 0, "changed": 1, "removed": 2}
    records.sort(key=lambda r: (order[r["op"]], json.dumps(r["key"], sort_keys=True, ensure_ascii=False)))

    stats = {
        "format": DIFF_FORMAT,
        "added": added,
        "removed": removed,
        "changed": changed,
        "unchanged": unchanged,
        "rows_from": len(before_rows),
        "rows_to": len(after_rows),
        "fields_added": [c for c in after_cols if c not in before_cols],
        "fields_removed": [c for c in before_cols if c not in after_cols],
        "duplicate_keys_from": dup_before,
        "duplicate_keys_to": dup_after,
        # How many `changed` records touched each column, commonest first.
        # This is the one question the old whole-row payload answered that
        # the slim one cannot: "which column moved this time?".
        "changed_fields": dict(changed_fields.most_common()),
    }
    return records, stats


def diff_path(feed_id: str, from_version: str, to_version: str, root: Path | None = None) -> Path:
    directory = (root or repo_root()) / "diffs" / feed_id
    return directory / ("%s__%s.jsonl" % (from_version, to_version))


def diff_versions(
    feed_id: str,
    from_version: str,
    to_version: str,
    key_fields: list[str],
    root: Path | None = None,
) -> dict:
    """Diff two stored versions and write the JSONL plus its summary."""
    root = root or repo_root()
    before = read_version(feed_id, from_version, root)
    after = read_version(feed_id, to_version, root)
    records, stats = diff_frames(before, after, key_fields)

    jsonl_path = diff_path(feed_id, from_version, to_version, root)
    jsonl_path.parent.mkdir(parents=True, exist_ok=True)
    with open(jsonl_path, "w", encoding="utf-8", newline="\n") as fh:
        for record in records:
            fh.write(json.dumps(record, ensure_ascii=False, sort_keys=True))
            fh.write("\n")

    summary = {
        "feed": feed_id,
        "from_version": from_version,
        "to_version": to_version,
        "key_fields": list(key_fields),
        "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "diff_file": jsonl_path.name,
    }
    summary.update(stats)
    summary_path = jsonl_path.parent / (jsonl_path.stem + ".summary.json")
    with open(summary_path, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(summary, fh, indent=2, ensure_ascii=False, sort_keys=True)
        fh.write("\n")
    return summary
