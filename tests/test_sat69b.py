import json
from pathlib import Path

import pandas as pd
import pytest
import requests

from govdiff.config import RAW_KEEP_MAX_BYTES, load_feeds
from govdiff.errors import FeedError
from govdiff.feeds import sat69b
from govdiff.runner import run_feed

FIXTURE = Path(__file__).parent / "fixtures" / "sat69b_sample.csv"
REPO = Path(__file__).parents[1]

# Eleven rows cut verbatim from the real 2026-01-22 file, keeping both preamble
# lines and the header row: all four situacion categories, one RFC that repeats
# with the same situacion under two different presumption oficios, a cell with
# two dates, a cell with an unformatted Excel serial, two suppressed rows that
# share an oficio, and at least one 0x80-0x9F byte so the file is genuinely
# cp1252 rather than merely latin-1-compatible.


@pytest.fixture(scope="module")
def content():
    return FIXTURE.read_bytes()


@pytest.fixture(scope="module")
def parsed(content):
    return sat69b.parse(content)


# ---------------------------------------------------------------------------
# Encoding
# ---------------------------------------------------------------------------


def test_the_real_file_is_cp1252(content):
    assert sat69b.detect_encoding(content) == "cp1252"


def test_cp1252_is_not_guessed_when_the_bytes_say_utf8():
    # utf-8-sig is tried first and reads BOM-less utf-8 too, so a utf-8 file
    # is never mis-read as a single-byte encoding.
    assert sat69b.detect_encoding("No,RFC\n1,Ñ".encode("utf-8")) == "utf-8-sig"
    assert sat69b.detect_encoding("No,RFC\n1,Ñ".encode("utf-8-sig")) == "utf-8-sig"


def test_latin1_is_only_chosen_when_the_c1_range_is_unused():
    # 0xF1 is n-with-tilde in both encodings, so nothing distinguishes them.
    assert sat69b.detect_encoding(b"No,RFC\r\n1,SE\xf1OR") == "latin-1"
    # 0x93 is a curly quote in cp1252 and an unprintable control in latin-1.
    assert sat69b.detect_encoding(b"No,RFC\r\n1,\x93SE\xf1OR\x94") == "cp1252"


def test_decoding_the_fixture_as_latin1_would_corrupt_it(content):
    assert "“" in content.decode("cp1252")
    assert "“" not in content.decode("latin-1")


# ---------------------------------------------------------------------------
# Header detection
# ---------------------------------------------------------------------------


def test_the_header_sits_under_two_title_rows(content):
    lines = content.decode("cp1252").splitlines()
    assert sat69b.find_header_row(lines) == 2


def test_the_preamble_is_the_two_sat_title_rows(content):
    preamble = sat69b.preamble(content)
    assert len(preamble) == 2
    assert preamble[0].startswith('"Informaci')
    assert preamble[1].startswith("Listado completo de contribuyentes")


def test_a_padded_preamble_row_is_not_mistaken_for_the_header():
    # The first title row parses to one label and nineteen empty fields.
    lines = ['"Aviso legal",,,,,,,', "Listado completo,,,,,,,", "No,RFC,Nombre,Situacion"]
    assert sat69b.find_header_row(lines) == 2


def test_a_file_without_an_rfc_column_is_an_error():
    with pytest.raises(FeedError):
        sat69b.find_header_row(["a,b,c", "1,2,3"])


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------


def test_columns_are_snake_case_and_the_ordinal_is_dropped(parsed):
    assert parsed.columns[0] == "rfc"
    assert "no" not in parsed.columns
    assert "situacion_del_contribuyente" in parsed.columns
    assert "numero_y_fecha_de_oficio_global_de_presuncion_sat" in parsed.columns


def test_values_are_text_and_whitespace_is_normalised(parsed):
    assert all(str(dtype) == "string" for dtype in parsed.dtypes)
    oficios = parsed["numero_y_fecha_de_oficio_global_de_presuncion_sat"]
    assert not any("  " in v for v in oficios)
    assert not any(v != v.strip() for v in oficios)


def test_every_situacion_category_is_present(parsed):
    assert set(sat69b.situacion_counts(parsed)) == {
        "Presunto",
        "Desvirtuado",
        "Definitivo",
        "Sentencia Favorable",
    }


def test_dates_keep_the_source_string_and_gain_an_iso_sibling(parsed):
    row = parsed[parsed["rfc"].eq("AAA080808HL8")].iloc[0]
    assert row["publicacion_pagina_sat_presuntos"] == "01/06/2018"
    assert row["publicacion_pagina_sat_presuntos_iso"] == "2018-06-01"


def test_an_ambiguous_date_cell_gets_no_iso_sibling():
    # Two dates in one cell, and a raw Excel serial SAT never formatted.
    assert sat69b.iso_date("25/05/2022 - 26/04/2021") is None
    assert sat69b.iso_date("44014") is None
    assert sat69b.iso_date("") is None
    assert sat69b.iso_date(None) is None
    assert sat69b.iso_date("31/02/2020") is None
    assert sat69b.iso_date("30/09/2016") == "2016-09-30"


def test_the_fixture_carries_both_ambiguous_date_forms(parsed):
    # AEHE660309SE6 has an Excel serial SAT never formatted back to a date.
    serial = parsed[parsed["rfc"].eq("AEHE660309SE6")].iloc[0]
    assert serial["publicacion_dof_presuntos"] == "44014"
    assert pd.isna(serial["publicacion_dof_presuntos_iso"])

    # AAA140116926 has two dates in one cell, on both definitivos columns.
    two_dates = parsed[parsed["rfc"].eq("AAA140116926")].iloc[0]
    assert two_dates["publicacion_pagina_sat_definitivos"] == "25/05/2022 - 26/04/2021"
    assert pd.isna(two_dates["publicacion_pagina_sat_definitivos_iso"])
    assert pd.isna(two_dates["publicacion_dof_definitivos_iso"])


def test_every_date_column_gets_its_iso_sibling_next_to_it(parsed):
    columns = list(parsed.columns)
    dated = [c for c in columns if c.startswith("publicacion_") and not c.endswith("_iso")]
    assert len(dated) == 8
    for column in dated:
        assert columns[columns.index(column) + 1] == column + "_iso"


# ---------------------------------------------------------------------------
# The key
# ---------------------------------------------------------------------------


def test_rfc_alone_is_not_a_key(parsed):
    assert parsed["rfc"].duplicated().any()


def test_rfc_plus_situacion_is_not_a_key_either(parsed):
    # CAL140908936 is Definitivo twice, from two unrelated proceedings.
    pair = parsed[parsed["rfc"].eq("CAL140908936")]
    assert len(pair) == 2
    assert pair["situacion_del_contribuyente"].nunique() == 1


def test_rfc_plus_presumption_oficio_is_unique_for_every_real_rfc(parsed):
    real = parsed[parsed["rfc"].ne(sat69b.SUPPRESSED_RFC)]
    assert len(real) > 0
    assert not real[sat69b.KEY_FIELDS].duplicated().any()


def test_only_the_court_suppressed_rows_share_a_key(parsed):
    duplicated = parsed[parsed[sat69b.KEY_FIELDS].duplicated(keep=False)]
    assert set(duplicated["rfc"]) == {sat69b.SUPPRESSED_RFC}


def test_the_situacion_is_deliberately_not_part_of_the_key():
    # A taxpayer moving Presunto -> Definitivo has to read as one change, not
    # as a removal plus an addition. That is the whole point of this feed.
    assert "situacion_del_contribuyente" not in sat69b.KEY_FIELDS


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


def test_registry_points_at_this_module():
    feed = load_feeds(REPO / "feeds.yaml")["sat69b"]
    assert feed.enabled is True
    assert feed.parser == "govdiff.feeds.sat69b"
    assert feed.key_fields == sat69b.KEY_FIELDS
    assert feed.document_url == sat69b.DOCUMENT_URL
    assert feed.listing_url is None
    assert feed.load_parser() is sat69b


def test_list_versions_reports_the_one_live_document_and_makes_no_request():
    entries = sat69b.list_versions()
    assert len(entries) == 1
    assert entries[0]["url"] == sat69b.DOCUMENT_URL
    assert entries[0]["date"] is None


# ---------------------------------------------------------------------------
# The nightly run
# ---------------------------------------------------------------------------


class FakeResponse:
    def __init__(self, status, headers, content):
        self.status_code = status
        self.headers = headers
        self.content = content

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError("status %d" % self.status_code)

    def close(self):
        pass


class FakeSat:
    """Answers 200 the first time and 304 to a matching If-Modified-Since."""

    LAST_MODIFIED = "Thu, 22 Jan 2026 22:59:33 GMT"
    ETAG = '"{E8180FE0-2E1C-4445-9381-A355CB4CFD85},24"'

    def __init__(self, body):
        self.body = body
        self.calls = []

    def request(self, method, url, headers=None, timeout=None, allow_redirects=True):
        headers = dict(headers or {})
        self.calls.append({"url": url, "headers": headers})
        common = {
            "Content-Type": "application/octet-stream",
            "Last-Modified": self.LAST_MODIFIED,
            "ETag": self.ETAG,
        }
        if headers.get("If-Modified-Since") == self.LAST_MODIFIED:
            return FakeResponse(304, common, b"")
        return FakeResponse(200, dict(common, **{"Content-Length": str(len(self.body))}), self.body)


@pytest.fixture()
def repo(tmp_path):
    (tmp_path / "feeds.yaml").write_bytes((REPO / "feeds.yaml").read_bytes())
    return tmp_path


def test_run_snapshots_once_then_reports_unchanged(repo, content):
    sat = FakeSat(content)

    first = run_feed("sat69b", repo, session=sat)
    assert first["created"] is True
    assert first["version_id"].startswith("2026-01-22-")
    assert first["row_count"] == 11
    # One version, so there is nothing to diff and none is invented.
    assert first["diff"] is None
    assert not (repo / "diffs" / "sat69b").exists()
    # The fixture is 5 KB so a raw copy is kept here; the 4.4 MB production
    # file is over RAW_KEEP_MAX_BYTES, so none is committed for the real feed.
    assert len(content) < RAW_KEEP_MAX_BYTES
    assert Path(first["raw_kept"]).exists()

    second = run_feed("sat69b", repo, session=sat)
    assert second["created"] is False
    assert second["note"] == "304 Not Modified"
    assert second["version_id"] == first["version_id"]
    assert first["diff"] is None and second["diff"] is None


def test_the_second_run_asks_on_last_modified_and_not_on_the_etag(repo, content):
    sat = FakeSat(content)
    run_feed("sat69b", repo, session=sat)
    run_feed("sat69b", repo, session=sat)

    assert len(sat.calls) == 2
    assert sat.calls[0]["headers"].get("If-Modified-Since") is None
    conditional = sat.calls[1]["headers"]
    assert conditional["If-Modified-Since"] == FakeSat.LAST_MODIFIED
    # SAT's SharePoint ETag is recorded but is never used as a validator.
    assert "If-None-Match" not in conditional


def test_both_validators_are_recorded_even_though_only_one_is_used(repo, content):
    run_feed("sat69b", repo, session=FakeSat(content))

    state = json.loads((repo / ".state" / "sat69b.json").read_text(encoding="utf-8"))
    assert state["last_modified"] == FakeSat.LAST_MODIFIED
    assert state["etag"] == FakeSat.ETAG
    assert state["sha256"]
    assert state["version_count"] == 1
