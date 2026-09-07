import json

import pandas as pd
import pytest

from govdiff.diff import diff_frames, diff_versions
from govdiff.errors import FeedError
from govdiff.snapshot import write_snapshot

KEY = ["code"]


def frame(rows):
    return pd.DataFrame(rows, dtype="string")


def by_op(records):
    grouped = {}
    for record in records:
        grouped.setdefault(record["op"], []).append(record)
    return grouped


def test_added_removed_and_changed():
    before = frame(
        [
            {"code": "000001", "name": "Integral", "rate": "0"},
            {"code": "000002", "name": "Via", "rate": "0"},
            {"code": "000003", "name": "Gone", "rate": "5"},
        ]
    )
    after = frame(
        [
            {"code": "000001", "name": "Integral", "rate": "0"},
            {"code": "000002", "name": "Exploracao de via", "rate": "0"},
            {"code": "000004", "name": "Novo", "rate": "60"},
        ]
    )

    records, stats = diff_frames(before, after, KEY)
    grouped = by_op(records)

    assert stats["added"] == 1
    assert stats["removed"] == 1
    assert stats["changed"] == 1
    assert stats["unchanged"] == 1
    assert stats["rows_from"] == 3
    assert stats["rows_to"] == 3

    assert grouped["added"][0]["key"] == {"code": "000004"}
    assert grouped["added"][0]["before"] is None
    assert grouped["added"][0]["after"]["name"] == "Novo"

    assert grouped["removed"][0]["key"] == {"code": "000003"}
    assert grouped["removed"][0]["after"] is None
    assert grouped["removed"][0]["before"]["rate"] == "5"

    changed = grouped["changed"][0]
    assert changed["key"] == {"code": "000002"}
    # Only the fields that actually moved are reported.
    assert changed["before"] == {"name": "Via"}
    assert changed["after"] == {"name": "Exploracao de via"}


def test_new_column_shows_as_a_change_and_is_reported():
    before = frame([{"code": "000001", "name": "Integral"}])
    after = frame([{"code": "000001", "name": "Integral", "anexo": "III"}])

    records, stats = diff_frames(before, after, KEY)

    assert stats["fields_added"] == ["anexo"]
    assert stats["fields_removed"] == []
    assert stats["changed"] == 1
    assert records[0]["before"] == {"anexo": None}
    assert records[0]["after"] == {"anexo": "III"}


def test_empty_and_missing_cells_compare_equal():
    before = frame([{"code": "000001", "note": None}])
    after = frame([{"code": "000001", "note": "   "}])

    records, stats = diff_frames(before, after, KEY)

    assert stats["changed"] == 0
    assert stats["unchanged"] == 1
    assert records == []


def test_duplicate_keys_are_kept_apart_not_merged():
    # The 2024-12-07 cClassTrib release really does ship code 200003 twice.
    before = frame(
        [
            {"code": "200003", "name": "Emergencia"},
            {"code": "200003", "name": "Acessibilidade"},
        ]
    )
    after = frame([{"code": "200003", "name": "Emergencia"}])

    records, stats = diff_frames(before, after, KEY)

    assert stats["duplicate_keys_from"] == 1
    assert stats["duplicate_keys_to"] == 0
    assert stats["removed"] == 1
    assert stats["unchanged"] == 1
    removed = by_op(records)["removed"][0]
    assert removed["key"] == {"code": "200003", "_occurrence": 2}
    assert removed["before"]["name"] == "Acessibilidade"


def test_missing_key_field_is_an_error():
    before = frame([{"other": "x"}])
    after = frame([{"other": "y"}])
    with pytest.raises(FeedError):
        diff_frames(before, after, KEY)


def test_no_key_fields_is_an_error():
    with pytest.raises(FeedError):
        diff_frames(frame([{"code": "1"}]), frame([{"code": "1"}]), [])


def test_diff_versions_writes_jsonl_and_summary(tmp_path):
    before = frame([{"code": "000001", "name": "Integral"}])
    after = frame([{"code": "000001", "name": "Integral total"}, {"code": "000002", "name": "Via"}])

    first = write_snapshot(
        "demo", before, source_url="http://example.invalid/a", sha256="a" * 64,
        fetched_at="2026-09-01T00:00:00+00:00", key_fields=KEY, root=tmp_path,
    )
    second = write_snapshot(
        "demo", after, source_url="http://example.invalid/b", sha256="b" * 64,
        fetched_at="2026-09-02T00:00:00+00:00", key_fields=KEY, root=tmp_path,
    )

    summary = diff_versions("demo", first.version_id, second.version_id, KEY, tmp_path)

    jsonl = tmp_path / "diffs" / "demo" / ("%s__%s.jsonl" % (first.version_id, second.version_id))
    summary_file = jsonl.parent / (jsonl.stem + ".summary.json")
    assert jsonl.exists() and summary_file.exists()

    lines = [json.loads(line) for line in jsonl.read_text(encoding="utf-8").splitlines()]
    assert len(lines) == 2
    assert {line["op"] for line in lines} == {"added", "changed"}

    on_disk = json.loads(summary_file.read_text(encoding="utf-8"))
    assert on_disk["added"] == summary["added"] == 1
    assert on_disk["changed"] == summary["changed"] == 1
    assert on_disk["from_version"] == first.version_id
    assert on_disk["to_version"] == second.version_id
