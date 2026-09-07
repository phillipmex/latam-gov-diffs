import json

import pandas as pd

from govdiff.snapshot import (
    find_version_by_sha,
    list_versions,
    read_meta,
    read_version,
    store_raw,
    version_id,
    write_snapshot,
)

SHA_A = "1" * 64
SHA_B = "2" * 64


def frame():
    return pd.DataFrame([{"code": "000001", "name": "Integral"}], dtype="string")


def test_version_id_prefers_the_publisher_date():
    http_date = "Thu, 03 Sep 2026 15:02:36 GMT"
    assert version_id(SHA_A, http_date, "2026-09-07T06:00:00+00:00") == "2026-09-03-11111111"


def test_version_id_accepts_a_plain_iso_date():
    # Bootstrap hands the differ the listing's publication date, not an HTTP date.
    assert version_id(SHA_A, "2025-12-15", None) == "2025-12-15-11111111"


def test_version_id_falls_back_to_the_fetch_date():
    assert version_id(SHA_A, None, "2026-09-07T06:00:00+00:00") == "2026-09-07-11111111"


def test_same_hash_never_creates_a_second_version(tmp_path):
    first = write_snapshot(
        "demo", frame(), source_url="http://example.invalid/f", sha256=SHA_A,
        fetched_at="2026-09-07T06:00:00+00:00", key_fields=["code"], root=tmp_path,
    )
    assert first.created is True

    again = write_snapshot(
        "demo", frame(), source_url="http://example.invalid/f", sha256=SHA_A,
        fetched_at="2026-09-08T06:00:00+00:00", key_fields=["code"], root=tmp_path,
    )
    assert again.created is False
    assert again.version_id == first.version_id
    assert again.row_count == 1
    assert list_versions("demo", tmp_path) == [first.version_id]


def test_new_hash_creates_a_new_version(tmp_path):
    write_snapshot(
        "demo", frame(), source_url="http://example.invalid/f", sha256=SHA_A,
        fetched_at="2026-09-07T06:00:00+00:00", key_fields=["code"], root=tmp_path,
    )
    other = pd.DataFrame([{"code": "000002", "name": "Via"}], dtype="string")
    second = write_snapshot(
        "demo", other, source_url="http://example.invalid/f", sha256=SHA_B,
        fetched_at="2026-09-08T06:00:00+00:00", key_fields=["code"], root=tmp_path,
    )
    assert second.created is True
    assert len(list_versions("demo", tmp_path)) == 2
    assert find_version_by_sha("demo", SHA_B, tmp_path) == second.version_id
    assert find_version_by_sha("demo", "9" * 64, tmp_path) is None


def test_sidecar_carries_the_required_fields(tmp_path):
    result = write_snapshot(
        "demo", frame(), source_url="http://example.invalid/f", sha256=SHA_A,
        fetched_at="2026-09-07T06:00:00+00:00", last_modified="2026-09-06",
        key_fields=["code"], extra={"published": "06/09/2026"}, root=tmp_path,
    )
    meta = json.loads((result.path / "meta.json").read_text(encoding="utf-8"))
    for field in ("schema", "source_url", "fetched_at", "last_modified", "sha256", "row_count"):
        assert field in meta
    assert meta["row_count"] == 1
    assert meta["published"] == "06/09/2026"
    assert [column["name"] for column in meta["schema"]] == ["code", "name"]

    restored = read_version("demo", result.version_id, tmp_path)
    assert list(restored["code"]) == ["000001"]
    assert read_meta("demo", result.version_id, tmp_path)["sha256"] == SHA_A


def test_raw_is_kept_when_small_and_dropped_when_large(tmp_path):
    small = store_raw("demo", b"x" * 1024, "small.xlsx", "2026-09-07", tmp_path)
    assert small is not None and small.exists()

    big = store_raw("demo", b"x" * (3 * 1024 * 1024), "big.xls", "2026-09-07", tmp_path)
    assert big is None
    assert not (tmp_path / "raw" / "demo" / "2026-09-07" / "big.xls").exists()
