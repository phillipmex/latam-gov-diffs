"""The change feed: docs/feed.xml, docs/<feed>/feed.xml and CHANGES.md.

Two things are checked hard because they are what makes the files safe to
commit every night: the Atom is well-formed and carries every element a reader
requires, and the output is byte-identical when the archive has not moved.
"""

import json
import xml.etree.ElementTree as ET

from govdiff.changefeed import (
    CHANGES_JSON_FORMAT,
    SITE_URL,
    build_changes_json,
    build_entries,
    entry_id,
    render_atom,
    render_changes,
    render_changes_json,
    write_change_feed,
)
from govdiff.cli import main
from govdiff.config import HEAD_START_HOURS
from govdiff.index import build_index

ATOM = "{http://www.w3.org/2005/Atom}"

FEEDS_YAML = """\
feeds:
  - id: alpha
    name: Alpha table & friends
    country: BR
    publisher: Alpha publisher <office>
    enabled: true
    listing_url: "http://example.invalid/list"
    document_url: "http://example.invalid/doc.xlsx"
    format: xlsx
    parser: govdiff.feeds.cclasstrib
    key_fields: [code]
  - id: zulu
    name: Zulu list
    country: MX
    publisher: Zulu publisher
    enabled: true
    listing_url: null
    document_url: "http://example.invalid/other.csv"
    format: csv
    parser: null
    key_fields: [rfc]
"""


def _version(root, feed, vid, *, rows=10):
    directory = root / "data" / feed / vid
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "data.parquet").write_bytes(b"PAR1notreallyparquet")
    meta = {
        "feed": feed,
        "version_id": vid,
        "row_count": rows,
        "sha256": "a" * 64,
        "source_url": "http://example.invalid/doc.xlsx",
        "fetched_at": "2026-09-07T06:00:00+00:00",
        "last_modified": None,
        "key_fields": ["code"],
        "schema": [{"name": "code", "dtype": "string"}],
    }
    with open(directory / "meta.json", "w", encoding="utf-8", newline="\n") as fh:
        json.dump(meta, fh, indent=2, sort_keys=True)
        fh.write("\n")


def _diff(root, feed, frm, to, *, added, changed, removed, generated_at, fields=None):
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
        "fields_added": ["brand new & shiny"],
        "fields_removed": [],
        "changed_fields": fields if fields is not None else {"label": changed, "note": 1},
        "generated_at": generated_at,
        "key_fields": ["code"],
        "duplicate_keys_from": 0,
        "duplicate_keys_to": 0,
    }
    with open(directory / (stem + ".summary.json"), "w", encoding="utf-8", newline="\n") as fh:
        json.dump(summary, fh, indent=2, sort_keys=True)
        fh.write("\n")


def archive(tmp_path):
    """A two-feed archive: alpha has two diffs, zulu has a version and none."""
    root = tmp_path / "archive"
    root.mkdir(exist_ok=True)
    (root / "feeds.yaml").write_text(FEEDS_YAML, encoding="utf-8")
    _version(root, "alpha", "2026-01-01-aaaaaaaa")
    _version(root, "alpha", "2026-04-15-bbbbbbbb")
    _version(root, "alpha", "2026-06-23-cccccccc")
    _diff(
        root,
        "alpha",
        "2026-01-01-aaaaaaaa",
        "2026-04-15-bbbbbbbb",
        added=1,
        changed=2,
        removed=3,
        generated_at="2026-09-07T06:00:00+00:00",
    )
    _diff(
        root,
        "alpha",
        "2026-04-15-bbbbbbbb",
        "2026-06-23-cccccccc",
        added=8,
        changed=156,
        removed=0,
        generated_at="2026-09-07T06:31:26+00:00",
        fields={"dataatualizacao": 156, "indnfgas": 12, "anexo": 12, "lc_redacao": 3},
    )
    _version(root, "zulu", "2026-02-02-dddddddd")
    return root


# ------------------------------------------------------------------ entries


def test_entries_are_newest_first_across_every_feed(tmp_path):
    entries = build_entries(archive(tmp_path))
    assert [e["to"] for e in entries] == ["2026-06-23-cccccccc", "2026-04-15-bbbbbbbb"]


def test_entry_ids_are_stable_tag_uris_and_unique(tmp_path):
    root = archive(tmp_path)
    entries = build_entries(root)
    ids = [entry_id(e) for e in entries]
    assert len(set(ids)) == len(ids)
    assert ids[0] == (
        "tag:phillipmex.github.io,2026:latam-gov-diffs/alpha/"
        "2026-04-15-bbbbbbbb__2026-06-23-cccccccc"
    )
    # Rebuilding from the same archive must produce the same ids.
    assert [entry_id(e) for e in build_entries(root)] == ids


# --------------------------------------------------------------------- atom


def _parse(xml_text):
    return ET.fromstring(xml_text)


def test_atom_is_well_formed_and_has_the_required_feed_elements(tmp_path):
    root = archive(tmp_path)
    index = build_index(root)
    tree = _parse(render_atom(index, build_entries(root, index)))
    assert tree.tag == ATOM + "feed"
    for name in ("id", "title", "updated", "author"):
        assert tree.find(ATOM + name) is not None, name
    rels = {link.get("rel"): link.get("href") for link in tree.findall(ATOM + "link")}
    assert rels["self"].endswith("/feed.xml")
    assert rels["alternate"] == SITE_URL


def test_every_entry_has_id_title_updated_link_and_content(tmp_path):
    root = archive(tmp_path)
    index = build_index(root)
    tree = _parse(render_atom(index, build_entries(root, index)))
    entries = tree.findall(ATOM + "entry")
    assert len(entries) == 2
    for entry in entries:
        for name in ("id", "title", "updated", "content"):
            assert entry.find(ATOM + name) is not None, name
        assert entry.find(ATOM + "content").get("type") == "text"
        links = {link.get("rel"): link for link in entry.findall(ATOM + "link")}
        assert links["alternate"].get("type") == "text/html"
        assert links["enclosure"].get("type") == "application/x-ndjson"
        assert int(links["enclosure"].get("length")) > 0


def test_entry_title_carries_the_dates_and_the_three_counts(tmp_path):
    root = archive(tmp_path)
    index = build_index(root)
    tree = _parse(render_atom(index, build_entries(root, index)))
    title = tree.findall(ATOM + "entry")[0].find(ATOM + "title").text
    assert title == "alpha 2026-04-15 → 2026-06-23: +8 / ~156 / −0"


def test_entry_links_are_a_viewer_deep_link_and_the_raw_jsonl(tmp_path):
    root = archive(tmp_path)
    index = build_index(root)
    tree = _parse(render_atom(index, build_entries(root, index)))
    links = {
        link.get("rel"): link.get("href")
        for link in tree.findall(ATOM + "entry")[0].findall(ATOM + "link")
    }
    assert links["alternate"] == (
        SITE_URL + "#feed=alpha&from=2026-04-15-bbbbbbbb&to=2026-06-23-cccccccc"
    )
    assert links["enclosure"].startswith("https://raw.githubusercontent.com/")
    assert links["enclosure"].endswith(
        "/diffs/alpha/2026-04-15-bbbbbbbb__2026-06-23-cccccccc.jsonl"
    )


def test_content_names_the_counts_and_the_columns_that_moved(tmp_path):
    root = archive(tmp_path)
    index = build_index(root)
    tree = _parse(render_atom(index, build_entries(root, index)))
    body = tree.findall(ATOM + "entry")[0].find(ATOM + "content").text
    assert "8 added, 156 changed, 0 removed" in body
    assert "dataatualizacao (156)" in body
    # Ties break by name, so anexo precedes indnfgas at the same count.
    assert body.index("anexo (12)") < body.index("indnfgas (12)")
    assert "Columns the publisher added: brand new & shiny." in body


def test_feed_updated_is_the_newest_diffs_timestamp_not_now(tmp_path):
    root = archive(tmp_path)
    index = build_index(root)
    tree = _parse(render_atom(index, build_entries(root, index)))
    assert tree.find(ATOM + "updated").text == "2026-09-07T06:31:26+00:00"


def test_a_feed_with_no_diff_still_renders_a_valid_empty_atom(tmp_path):
    root = archive(tmp_path)
    index = build_index(root)
    tree = _parse(render_atom(index, build_entries(root, index), feed_id="zulu"))
    assert tree.findall(ATOM + "entry") == []
    # Falls back to the newest archived version's date, never to now().
    assert tree.find(ATOM + "updated").text == "2026-02-02T00:00:00+00:00"
    assert tree.find(ATOM + "id").text.endswith("/zulu")


def test_a_per_feed_atom_carries_only_that_feed(tmp_path):
    root = archive(tmp_path)
    index = build_index(root)
    tree = _parse(render_atom(index, build_entries(root, index), feed_id="alpha"))
    assert len(tree.findall(ATOM + "entry")) == 2
    for entry in tree.findall(ATOM + "entry"):
        assert entry.find(ATOM + "category").get("term") == "alpha"


def test_markup_in_publisher_names_is_escaped_not_injected(tmp_path):
    root = archive(tmp_path)
    index = build_index(root)
    xml_text = render_atom(index, build_entries(root, index), feed_id="alpha")
    assert "<office>" not in xml_text
    assert "&lt;office&gt;" in xml_text
    tree = _parse(xml_text)  # would raise if the escaping were wrong
    assert "Alpha publisher <office>" in tree.find(ATOM + "subtitle").text


# -------------------------------------------------------------- CHANGES.md


def test_changes_md_says_it_is_generated_and_by_what(tmp_path):
    root = archive(tmp_path)
    index = build_index(root)
    body = render_changes(index, build_entries(root, index))
    assert body.startswith("# Changes\n")
    assert "Generated by `govdiff index`" in body.splitlines()[4]


def test_changes_md_has_one_section_per_feed_newest_row_first(tmp_path):
    root = archive(tmp_path)
    index = build_index(root)
    body = render_changes(index, build_entries(root, index))
    assert "## alpha" in body and "## zulu" in body
    rows = [line for line in body.splitlines() if line.startswith("| 2026-")]
    assert rows[0].startswith("| 2026-06-23 |")
    assert rows[1].startswith("| 2026-04-15 |")
    assert "| 8 | 156 | 0 |" in rows[0]
    assert "`dataatualizacao` (156)" in rows[0]
    assert "+1 more" in rows[0]  # four columns moved, three are named
    assert "diffs/alpha/2026-04-15-bbbbbbbb__2026-06-23-cccccccc.jsonl" in rows[0]


def test_changes_md_says_so_when_a_feed_has_no_change_yet(tmp_path):
    root = archive(tmp_path)
    index = build_index(root)
    body = render_changes(index, build_entries(root, index))
    assert "No change recorded yet." in body.split("## zulu")[1]


# ------------------------------------------------------------- determinism


def test_writing_twice_produces_identical_bytes(tmp_path):
    root = archive(tmp_path)
    first = write_change_feed(root)
    assert first["entries"] == 2
    assert sorted(first["written"]) == [
        "CHANGES.md",
        "docs/alpha/changes.json",
        "docs/alpha/feed.xml",
        "docs/feed.xml",
        "docs/zulu/changes.json",
        "docs/zulu/feed.xml",
    ]
    before = {p: (root / p).read_bytes() for p in first["written"]}
    second = write_change_feed(root)
    assert second["written"] == []
    assert sorted(second["unchanged"]) == sorted(before)
    for path, body in before.items():
        assert (root / path).read_bytes() == body


def test_a_new_diff_rewrites_the_feed(tmp_path):
    root = archive(tmp_path)
    write_change_feed(root)
    _version(root, "alpha", "2026-08-01-eeeeeeee")
    _diff(
        root,
        "alpha",
        "2026-06-23-cccccccc",
        "2026-08-01-eeeeeeee",
        added=4,
        changed=0,
        removed=0,
        generated_at="2026-09-08T06:00:00+00:00",
    )
    report = write_change_feed(root)
    assert "docs/feed.xml" in report["written"]
    assert "CHANGES.md" in report["written"]
    assert report["updated"] == "2026-09-08T06:00:00+00:00"
    tree = _parse((root / "docs" / "feed.xml").read_text(encoding="utf-8"))
    assert len(tree.findall(ATOM + "entry")) == 3


# --------------------------------------------------------------------- CLI


def test_govdiff_index_writes_the_change_feed_too(tmp_path, capsys):
    root = archive(tmp_path)
    assert main(["--repo", str(root), "index"]) == 0
    out = capsys.readouterr().out
    assert "docs/index.json" in out
    assert "change feed: 2 entry(s)" in out
    assert (root / "docs" / "feed.xml").exists()
    assert (root / "docs" / "alpha" / "feed.xml").exists()
    assert (root / "CHANGES.md").exists()


def test_index_output_override_leaves_the_repository_alone(tmp_path):
    root = archive(tmp_path)
    target = tmp_path / "elsewhere" / "archive.json"
    assert main(["--repo", str(root), "index", "--output", str(target)]) == 0
    assert target.exists()
    assert not (root / "docs").exists()
    assert not (root / "CHANGES.md").exists()


def test_no_change_feed_flag_writes_only_the_index(tmp_path):
    root = archive(tmp_path)
    assert main(["--repo", str(root), "index", "--no-change-feed"]) == 0
    assert (root / "docs" / "index.json").exists()
    assert not (root / "docs" / "feed.xml").exists()
    assert not (root / "CHANGES.md").exists()


# ------------------------------------------------------- the real archive


def test_the_committed_change_feed_is_current():
    """docs/feed.xml and CHANGES.md must match what `govdiff index` builds."""
    from govdiff.config import repo_root

    root = repo_root()
    committed = root / "docs" / "feed.xml"
    if not committed.exists():  # pragma: no cover - only before the first run
        return
    index = build_index(root)
    entries = build_entries(root, index)
    assert committed.read_text(encoding="utf-8") == render_atom(index, entries)
    assert (root / "CHANGES.md").read_text(encoding="utf-8") == render_changes(index, entries)
    for feed in index["feeds"]:
        path = root / "docs" / feed["id"] / "feed.xml"
        assert path.read_text(encoding="utf-8") == render_atom(index, entries, feed_id=feed["id"])


# ------------------------------------------------- docs/<feed>/changes.json
#
# The per-feed JSON is what a paying subscriber's own tooling reads, and
# docs/paid.md documents its shape as a promise. These tests are that promise
# written down: the shape, the ordering, the paths, and - the one that costs
# money if it breaks - that a quiet night leaves the file byte-identical.


def _changes_json(root, feed):
    with open(root / "docs" / feed / "changes.json", encoding="utf-8") as fh:
        return json.load(fh)


def test_changes_json_has_the_documented_shape(tmp_path):
    root = archive(tmp_path)
    assert main(["--repo", str(root), "index"]) == 0

    doc = _changes_json(root, "alpha")
    assert doc["format"] == CHANGES_JSON_FORMAT
    assert doc["feed"] == "alpha"
    assert doc["head_start_hours"] == HEAD_START_HOURS
    assert doc["path_base"] == "repository-root"
    assert doc["generated_at"].endswith("+00:00")

    # Newest first, and `latest` is the head of that list, not a second copy
    # assembled somewhere else.
    published = [c["published"] for c in doc["changes"]]
    assert published == sorted(published, reverse=True)
    assert doc["latest"] == doc["changes"][0]
    assert doc["change_count"] == len(doc["changes"])

    # Every path is relative to the repository root and resolves on disk, so a
    # subscriber can open it without knowing anything about our layout.
    for change in doc["changes"]:
        for key in ("jsonl", "summary"):
            assert not change[key].startswith("/")
            assert (root / change[key]).exists()
        for key in ("from", "to", "published", "added", "changed", "removed",
                    "rows_from", "rows_to", "fields_added", "fields_removed"):
            assert key in change


def test_changes_json_is_written_for_a_feed_with_no_diffs(tmp_path):
    root = archive(tmp_path)
    assert main(["--repo", str(root), "index"]) == 0
    doc = _changes_json(root, "zulu")
    assert doc["changes"] == []
    assert doc["change_count"] == 0
    assert doc["latest"] is None


def test_changes_json_counts_match_the_index(tmp_path):
    root = archive(tmp_path)
    assert main(["--repo", str(root), "index"]) == 0
    with open(root / "docs" / "index.json", encoding="utf-8") as fh:
        index = json.load(fh)
    for feed in index["feeds"]:
        doc = _changes_json(root, feed["id"])
        assert doc["change_count"] == feed["diff_count"]


def test_changes_json_does_not_move_on_a_quiet_night(tmp_path):
    """The whole point: an unchanged archive produces an unchanged file.

    If `generated_at` moved every run, the nightly job would commit three
    files every night whether or not a publisher had touched anything, and
    "a byte-identical file means there is nothing to do" - which docs/paid.md
    says in as many words - would stop being true.
    """
    root = archive(tmp_path)
    assert main(["--repo", str(root), "index"]) == 0
    before = (root / "docs" / "alpha" / "changes.json").read_bytes()
    assert main(["--repo", str(root), "index"]) == 0
    assert (root / "docs" / "alpha" / "changes.json").read_bytes() == before


def test_changes_json_moves_when_a_diff_appears(tmp_path):
    root = archive(tmp_path)
    assert main(["--repo", str(root), "index"]) == 0
    before = _changes_json(root, "alpha")

    _version(root, "alpha", "2026-08-01-dddddddd")
    _diff(
        root,
        "alpha",
        "2026-06-23-cccccccc",
        "2026-08-01-dddddddd",
        added=4,
        changed=0,
        removed=0,
        generated_at="2026-09-07T06:00:00+00:00",
    )
    assert main(["--repo", str(root), "index"]) == 0
    after = _changes_json(root, "alpha")
    assert after["change_count"] == before["change_count"] + 1
    assert after["latest"]["to"] == "2026-08-01-dddddddd"


def test_the_committed_changes_json_is_current():
    """The three docs/<feed>/changes.json in this repository are up to date."""
    from govdiff.config import repo_root

    root = repo_root()
    if not (root / "docs" / "index.json").exists():  # pragma: no cover
        return
    index = build_index(root)
    entries = build_entries(root, index)
    for feed in index["feeds"]:
        path = root / "docs" / feed["id"] / "changes.json"
        assert path.exists(), "%s has no changes.json" % feed["id"]
        with open(path, encoding="utf-8") as fh:
            committed = json.load(fh)
        fresh = build_changes_json(
            feed["id"], entries, generated_at=committed["generated_at"]
        )
        assert render_changes_json(fresh) == path.read_text(encoding="utf-8")
