import json

from govdiff.cli import main
from govdiff.index import INDEX_FORMAT, build_index, render_index, write_index

FEEDS_YAML = """\
feeds:
  - id: demo
    name: Demo table
    country: BR
    publisher: Demo publisher
    enabled: true
    listing_url: "http://example.invalid/list"
    document_url: "http://example.invalid/doc.xlsx"
    format: xlsx
    parser: govdiff.feeds.cclasstrib
    key_fields: [code]
    notes: nothing
  - id: quiet
    name: Disabled table
    country: MX
    publisher: Other publisher
    enabled: false
    listing_url: null
    document_url: "http://example.invalid/other.csv"
    format: csv
    parser: null
    key_fields: [rfc]
"""


def _version(root, feed, vid, *, rows, sha, published=None):
    directory = root / "data" / feed / vid
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "data.parquet").write_bytes(b"PAR1notreallyparquet")
    meta = {
        "feed": feed,
        "version_id": vid,
        "row_count": rows,
        "sha256": sha,
        "source_url": "http://example.invalid/doc.xlsx",
        "fetched_at": "2026-09-07T06:00:00+00:00",
        "last_modified": None,
        "key_fields": ["code"],
        "schema": [{"name": "code", "dtype": "string"}, {"name": "label", "dtype": "string"}],
    }
    if published:
        meta["published"] = published
    with open(directory / "meta.json", "w", encoding="utf-8", newline="\n") as fh:
        json.dump(meta, fh, indent=2, sort_keys=True)
        fh.write("\n")


def _diff(root, feed, frm, to, *, added, changed, removed):
    directory = root / "diffs" / feed
    directory.mkdir(parents=True, exist_ok=True)
    stem = "%s__%s" % (frm, to)
    with open(directory / (stem + ".jsonl"), "w", encoding="utf-8", newline="\n") as fh:
        fh.write('{"op": "added"}\n')
    summary = {
        "feed": feed,
        "from_version": frm,
        "to_version": to,
        "diff_file": stem + ".jsonl",
        "format": 2,
        "added": added,
        "changed": changed,
        "removed": removed,
        "unchanged": 5,
        "rows_from": 10,
        "rows_to": 12,
        "fields_added": [],
        "fields_removed": [],
        "changed_fields": {"label": changed},
        "generated_at": "2026-09-07T06:00:00+00:00",
        "key_fields": ["code"],
        "duplicate_keys_from": 0,
        "duplicate_keys_to": 0,
    }
    with open(directory / (stem + ".summary.json"), "w", encoding="utf-8", newline="\n") as fh:
        json.dump(summary, fh, indent=2, sort_keys=True)
        fh.write("\n")


def archive(tmp_path):
    """A miniature repository: two feeds, three versions, two diffs."""
    (tmp_path / "feeds.yaml").write_text(FEEDS_YAML, encoding="utf-8")
    _version(tmp_path, "demo", "2025-01-01-aaaaaaaa", rows=10, sha="a" * 64, published="01/01/2025")
    _version(tmp_path, "demo", "2025-06-01-bbbbbbbb", rows=11, sha="b" * 64)
    _version(tmp_path, "demo", "2026-02-01-cccccccc", rows=12, sha="c" * 64)
    _diff(tmp_path, "demo", "2025-01-01-aaaaaaaa", "2025-06-01-bbbbbbbb",
          added=1, changed=2, removed=0)
    _diff(tmp_path, "demo", "2025-06-01-bbbbbbbb", "2026-02-01-cccccccc",
          added=3, changed=0, removed=1)
    state_dir = tmp_path / ".state"
    state_dir.mkdir(exist_ok=True)
    with open(state_dir / "demo.json", "w", encoding="utf-8", newline="\n") as fh:
        json.dump(
            {
                "feed": "demo",
                "etag": None,
                "last_error": None,
                "last_fetched_at": "2026-09-07T06:00:00+00:00",
                "last_modified": None,
                "last_result": "unchanged",
                "row_count": 12,
                "sha256": "c" * 64,
                "source_url": "http://example.invalid/doc.xlsx",
                "version_count": 3,
                "version_id": "2026-02-01-cccccccc",
            },
            fh,
            indent=2,
            sort_keys=True,
        )
        fh.write("\n")
    return tmp_path


def test_index_lists_every_feed_including_the_disabled_one(tmp_path):
    index = build_index(archive(tmp_path))
    assert index["format"] == INDEX_FORMAT
    assert index["feed_count"] == 2
    assert [f["id"] for f in index["feeds"]] == ["demo", "quiet"]
    quiet = index["feeds"][1]
    assert quiet["enabled"] is False
    assert quiet["versions"] == [] and quiet["diffs"] == []


def test_feed_metadata_comes_from_feeds_yaml(tmp_path):
    demo = build_index(archive(tmp_path))["feeds"][0]
    assert demo["title"] == "Demo table"
    assert demo["country"] == "BR"
    assert demo["publisher"] == "Demo publisher"
    assert demo["document_url"] == "http://example.invalid/doc.xlsx"
    assert demo["key_fields"] == ["code"]


def test_versions_are_oldest_first_with_row_counts_and_hashes(tmp_path):
    demo = build_index(archive(tmp_path))["feeds"][0]
    assert demo["version_count"] == 3
    assert [v["version_id"] for v in demo["versions"]] == [
        "2025-01-01-aaaaaaaa",
        "2025-06-01-bbbbbbbb",
        "2026-02-01-cccccccc",
    ]
    first = demo["versions"][0]
    assert first["date"] == "2025-01-01"
    assert first["row_count"] == 10
    assert first["column_count"] == 2
    assert first["sha256"] == "a" * 64
    assert first["published"] == "01/01/2025"
    assert demo["latest_version"] == "2026-02-01-cccccccc"


def test_paths_are_repo_root_relative_with_forward_slashes(tmp_path):
    demo = build_index(archive(tmp_path))["feeds"][0]
    assert demo["versions"][0]["parquet"] == "data/demo/2025-01-01-aaaaaaaa/data.parquet"
    assert demo["versions"][0]["meta"] == "data/demo/2025-01-01-aaaaaaaa/meta.json"
    diff = demo["diffs"][0]
    assert diff["jsonl"] == "diffs/demo/2025-01-01-aaaaaaaa__2025-06-01-bbbbbbbb.jsonl"
    assert diff["summary"] == "diffs/demo/2025-01-01-aaaaaaaa__2025-06-01-bbbbbbbb.summary.json"


def test_diffs_carry_the_summary_counts_in_chain_order(tmp_path):
    demo = build_index(archive(tmp_path))["feeds"][0]
    assert demo["diff_count"] == 2
    assert [(d["from"], d["to"]) for d in demo["diffs"]] == [
        ("2025-01-01-aaaaaaaa", "2025-06-01-bbbbbbbb"),
        ("2025-06-01-bbbbbbbb", "2026-02-01-cccccccc"),
    ]
    assert demo["diffs"][1]["added"] == 3
    assert demo["diffs"][1]["changed"] == 0
    assert demo["diffs"][1]["removed"] == 1
    assert demo["diffs"][1]["jsonl_bytes"] == len('{"op": "added"}\n')


def test_state_block_omits_the_fields_that_move_every_night(tmp_path):
    state = build_index(archive(tmp_path))["feeds"][0]["state"]
    assert state["version_id"] == "2026-02-01-cccccccc"
    assert state["sha256"] == "c" * 64
    # These change on every run whether or not the archive changed, so an index
    # carrying them would produce a pointless commit every night.
    assert "last_fetched_at" not in state
    assert "last_result" not in state


def test_render_is_sorted_two_space_indented_and_newline_terminated(tmp_path):
    text = render_index(build_index(archive(tmp_path)))
    assert text.endswith("}\n")
    assert '\n  "feed_count": 2,' in text
    keys = [line.strip().split('"')[1] for line in text.splitlines() if line.startswith('  "')]
    assert keys == sorted(keys)
    assert json.loads(text)["feed_count"] == 2


def test_write_leaves_the_file_alone_when_only_the_timestamp_would_move(tmp_path):
    root = archive(tmp_path)
    first = write_index(root)
    assert first["changed"] is True
    target = root / "docs" / "index.json"
    before = target.read_bytes()
    second = write_index(root)
    assert second["changed"] is False
    assert target.read_bytes() == before
    assert second["generated_at"] == first["generated_at"]


def test_write_rewrites_when_the_archive_moves(tmp_path):
    root = archive(tmp_path)
    write_index(root)
    _version(root, "demo", "2026-08-01-dddddddd", rows=13, sha="d" * 64)
    report = write_index(root)
    assert report["changed"] is True
    assert report["versions"] == 4
    index = json.loads((root / "docs" / "index.json").read_text(encoding="utf-8"))
    assert index["feeds"][0]["latest_version"] == "2026-08-01-dddddddd"


def test_write_reports_the_totals(tmp_path):
    report = write_index(archive(tmp_path))
    assert (report["feeds"], report["versions"], report["diffs"]) == (2, 3, 2)


def test_cli_index_writes_the_file(tmp_path, capsys):
    root = archive(tmp_path)
    assert main(["--root", str(root), "index"]) == 0
    assert (root / "docs" / "index.json").exists()
    out = capsys.readouterr().out
    assert "docs/index.json" in out and "3 version(s)" in out


def test_cli_index_honours_an_output_override(tmp_path):
    root = archive(tmp_path)
    target = tmp_path / "elsewhere" / "archive.json"
    assert main(["--root", str(root), "index", "--output", str(target)]) == 0
    assert target.exists()
    assert not (root / "docs").exists()


def test_the_committed_index_is_current(tmp_path):
    """docs/index.json in this repository must match what `govdiff index` builds."""
    from govdiff.config import repo_root

    root = repo_root()
    committed_path = root / "docs" / "index.json"
    if not committed_path.exists():  # pragma: no cover - only before the first run
        return
    committed = json.loads(committed_path.read_text(encoding="utf-8"))
    fresh = build_index(root, generated_at=committed["generated_at"])
    assert committed == fresh
