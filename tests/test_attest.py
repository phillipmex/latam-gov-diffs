"""The point-in-time attestation, built from the sat69b fixture.

Every test here works on a temporary archive made by parsing
`tests/fixtures/sat69b_sample.csv` - the same 11 rows cut byte-for-byte from
the real file that day 3's parser tests use - and writing it through the real
snapshot layer. Nothing here touches the network.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from govdiff.attest import (
    FEED_ID,
    attest,
    build_attestation,
    coverage,
    normalise_rfc,
    observations,
    records_for,
)
from govdiff.cli import main
from govdiff.errors import AttestationNotPossible
from govdiff.feeds import sat69b
from govdiff.snapshot import write_snapshot

FIXTURE = Path(__file__).parent / "fixtures" / "sat69b_sample.csv"

FEEDS_YAML = """\
feeds:
  - id: sat69b
    name: Listado completo 69-B
    country: MX
    publisher: Servicio de Administracion Tributaria (SAT)
    enabled: true
    listing_url: null
    document_url: "http://omawww.sat.gob.mx/cifras_sat/Documents/Listado_Completo_69-B.csv"
    format: csv
    parser: govdiff.feeds.sat69b
    key_fields: [rfc, numero_y_fecha_de_oficio_global_de_presuncion_sat]
"""

DOC_URL = "http://omawww.sat.gob.mx/cifras_sat/Documents/Listado_Completo_69-B.csv"


def _frame():
    return sat69b.parse(FIXTURE.read_bytes())


def _snapshot(root, frame, *, sha, fetched_at, last_modified):
    return write_snapshot(
        FEED_ID,
        frame,
        source_url=DOC_URL,
        sha256=sha,
        fetched_at=fetched_at,
        last_modified=last_modified,
        key_fields=sat69b.KEY_FIELDS,
        root=root,
    )


def _archive(tmp_path, *, second=False, state_stamp=None):
    """A miniature archive: one snapshot, optionally a second, later one."""
    root = tmp_path / "archive"
    root.mkdir()
    (root / "feeds.yaml").write_text(FEEDS_YAML, encoding="utf-8")

    frame = _frame()
    _snapshot(
        root,
        frame,
        sha="aaaaaaaa" + "0" * 56,
        fetched_at="2026-09-07T06:00:00+00:00",
        last_modified="Thu, 22 Jan 2026 22:59:33 GMT",
    )
    if second:
        moved = frame.copy()
        # One taxpayer moves Presunto -> Definitivo. That movement is the whole
        # reason this feed exists, so the attestation has to show it.
        mask = moved["rfc"] == "AAAA730727JE3"
        moved.loc[mask, "situacion_del_contribuyente"] = "Definitivo"
        _snapshot(
            root,
            moved,
            sha="bbbbbbbb" + "0" * 56,
            fetched_at="2026-09-20T06:00:00+00:00",
            last_modified="Fri, 18 Sep 2026 10:00:00 GMT",
        )

    stamp = state_stamp or ("2026-09-20T06:00:00+00:00" if second else "2026-09-07T06:00:00+00:00")
    state_dir = root / ".state"
    state_dir.mkdir(exist_ok=True)
    with open(state_dir / "sat69b.json", "w", encoding="utf-8", newline="\n") as fh:
        json.dump({"feed": FEED_ID, "last_fetched_at": stamp}, fh, indent=2, sort_keys=True)
        fh.write("\n")
    return root


# ------------------------------------------------------------------- helpers


def test_normalise_rfc_ignores_case_spaces_and_punctuation():
    assert normalise_rfc(" aaa080808hl8 ") == "AAA080808HL8"
    assert normalise_rfc("AAA-080808-HL8") == "AAA080808HL8"


def test_observations_are_oldest_first_with_their_provenance(tmp_path):
    root = _archive(tmp_path, second=True)
    obs = observations(root)
    assert [o.observed_on.isoformat() for o in obs] == ["2026-09-07", "2026-09-20"]
    assert obs[0].source_url == DOC_URL
    assert obs[0].last_modified == "Thu, 22 Jan 2026 22:59:33 GMT"
    assert obs[0].sha256.startswith("aaaaaaaa")
    assert obs[0].row_count == 11
    assert obs[0].parquet_bytes > 0


def test_coverage_ends_at_the_state_file_not_at_the_newest_snapshot(tmp_path):
    # A nightly run that finds the list unchanged writes no snapshot but does
    # stamp .state, and that is the honest end of what the archive observed.
    root = _archive(tmp_path, state_stamp="2026-10-15T06:00:00+00:00")
    start, end = coverage(root)
    assert start.isoformat() == "2026-09-07"
    assert end.isoformat() == "2026-10-15"


# -------------------------------------------------------------------- lookup


def test_records_for_reads_the_stage_columns(tmp_path):
    root = _archive(tmp_path)
    found = records_for("AAA080808HL8", observations(root)[0], root)
    assert len(found) == 1
    assert found[0]["situacion"] == "Sentencia Favorable"
    stages = {s["stage"]: s for s in found[0]["stages"]}
    assert "Presuncion - oficio global SAT" in stages
    assert stages["Presuncion - oficio global SAT"]["published"] == "01/06/2018"
    assert stages["Presuncion - oficio global SAT"]["published_iso"] == "2018-06-01"
    assert "Sentencia favorable - oficio global DOF" in stages
    # Desvirtuado never happened for this taxpayer, so those columns are empty
    # and no row is invented for them.
    assert not [s for s in found[0]["stages"] if s["stage"].startswith("Desvirtuado")]


def test_one_rfc_with_two_proceedings_is_reported_as_two_records(tmp_path):
    root = _archive(tmp_path)
    frame = _frame()
    counts = frame["rfc"].value_counts()
    repeated = [r for r, n in counts.items() if n > 1 and r != sat69b.SUPPRESSED_RFC]
    assert repeated, "the fixture is meant to carry one RFC twice"
    found = records_for(repeated[0], observations(root)[0], root)
    assert len(found) == 2
    oficios = {s["oficio"] for r in found for s in r["stages"] if "Presuncion" in s["stage"]}
    assert len(oficios) > 1


def test_a_missing_rfc_is_answered_no_rather_than_raising(tmp_path):
    root = _archive(tmp_path)
    report = build_attestation("ZZZ010101ZZ0", root=root, on="2026-09-07")
    assert report["segments"][0]["found"] is False
    assert "**No.**" in attest("ZZZ010101ZZ0", root=root, on="2026-09-07")


# --------------------------------------------------------------- the window


def test_the_snapshot_in_force_is_the_last_one_observed_on_or_before_the_day(tmp_path):
    root = _archive(tmp_path, second=True)
    early = build_attestation("AAAA730727JE3", root=root, on="2026-09-10")
    late = build_attestation("AAAA730727JE3", root=root, on="2026-09-20")
    assert early["segments"][0]["observation"].sha256.startswith("aaaaaaaa")
    assert late["segments"][0]["observation"].sha256.startswith("bbbbbbbb")
    assert early["segments"][0]["records"][0]["situacion"] == "Presunto"
    assert late["segments"][0]["records"][0]["situacion"] == "Definitivo"


def test_the_document_names_the_next_observation_so_the_edge_is_visible(tmp_path):
    root = _archive(tmp_path, second=True)
    report = build_attestation("AAA080808HL8", root=root, on="2026-09-10")
    window = report["segments"][0]["window"]
    assert window["next_version_id"].startswith("2026-09-18-bbbbbbbb")
    assert window["to"] == "2026-09-20 (exclusive)"
    text = attest("AAA080808HL8", root=root, on="2026-09-10")
    assert "Next observation" in text
    assert "2026-09-20T06:00:00+00:00" in text


def test_between_walks_every_snapshot_across_the_span(tmp_path):
    root = _archive(tmp_path, second=True)
    report = build_attestation("AAAA730727JE3", root=root, between=("2026-09-08", "2026-09-20"))
    assert len(report["segments"]) == 2
    assert [s["situaciones"] for s in report["segments"]] == [["Presunto"], ["Definitivo"]]
    text = attest("AAAA730727JE3", root=root, between=("2026-09-08", "2026-09-20"))
    assert "Yes, in part." in text
    assert "Presunto, Definitivo" in text
    assert "Evidence 1 of 2" in text and "Evidence 2 of 2" in text


def test_between_with_one_snapshot_says_throughout(tmp_path):
    root = _archive(tmp_path)
    text = attest("AAA080808HL8", root=root, between=("2026-09-07", "2026-09-07"))
    assert "Yes, throughout." in text


# ------------------------------------------------------------ honest limits


def test_a_date_before_the_first_snapshot_is_refused_and_says_why(tmp_path):
    root = _archive(tmp_path)
    with pytest.raises(AttestationNotPossible) as excinfo:
        build_attestation("AAA080808HL8", root=root, on="2026-08-01")
    message = str(excinfo.value)
    assert "2026-09-07" in message
    assert "no dated back-series" in message


def test_a_date_after_the_last_observation_is_refused(tmp_path):
    root = _archive(tmp_path)
    with pytest.raises(AttestationNotPossible) as excinfo:
        build_attestation("AAA080808HL8", root=root, on="2026-12-25")
    assert "after the last day this archive observed" in str(excinfo.value)


def test_exactly_one_question_is_required(tmp_path):
    root = _archive(tmp_path)
    with pytest.raises(AttestationNotPossible):
        build_attestation("AAA080808HL8", root=root)
    with pytest.raises(AttestationNotPossible):
        build_attestation(
            "AAA080808HL8", root=root, on="2026-09-07", between=("2026-09-07", "2026-09-07")
        )


def test_between_wants_the_earlier_date_first(tmp_path):
    root = _archive(tmp_path, second=True)
    with pytest.raises(AttestationNotPossible) as excinfo:
        build_attestation("AAA080808HL8", root=root, between=("2026-09-20", "2026-09-08"))
    assert "earlier date first" in str(excinfo.value)


def test_a_bad_date_is_refused_with_the_expected_format(tmp_path):
    root = _archive(tmp_path)
    with pytest.raises(AttestationNotPossible) as excinfo:
        build_attestation("AAA080808HL8", root=root, on="07/09/2026")
    assert "YYYY-MM-DD" in str(excinfo.value)


def test_an_empty_archive_cannot_attest_anything(tmp_path):
    root = tmp_path / "empty"
    root.mkdir()
    (root / "feeds.yaml").write_text(FEEDS_YAML, encoding="utf-8")
    with pytest.raises(AttestationNotPossible):
        build_attestation("AAA080808HL8", root=root, on="2026-09-07")


# ---------------------------------------------------------------- rendering


def test_the_document_carries_every_piece_of_evidence_it_promises(tmp_path):
    root = _archive(tmp_path)
    text = attest(
        "AAA080808HL8", root=root, on="2026-09-07", generated_at="2026-09-07T12:00:00+00:00"
    )
    assert text.startswith("# Point-in-time attestation - SAT listado 69-B")
    assert "| Subject RFC | `AAA080808HL8` |" in text
    assert "aaaaaaaa" + "0" * 56 in text  # the sha256 of the file SAT served
    assert DOC_URL in text  # the SAT document URL
    assert "Thu, 22 Jan 2026 22:59:33 GMT" in text  # Last-Modified at the time
    assert "`2026-01-22-aaaaaaaa`" in text  # the snapshot version id
    assert "Sentencia Favorable" in text
    assert "not legal advice" in text
    assert "not a substitute for SAT's own" in text
    assert "Coverage begins 2026-09-07" in text
    assert "govdiff attest sat69b --rfc AAA080808HL8 --on 2026-09-07" in text
    assert "| Issued | 2026-09-07T12:00:00+00:00 |" in text
    assert "the latam-gov-diffs maintainers" in text


def test_rendering_is_deterministic_for_a_fixed_issue_time(tmp_path):
    root = _archive(tmp_path)
    first = attest("AAA080808HL8", root=root, on="2026-09-07", generated_at="2026-09-07T12:00:00Z")
    second = attest("AAA080808HL8", root=root, on="2026-09-07", generated_at="2026-09-07T12:00:00Z")
    assert first == second


# ---------------------------------------------------------------------- CLI


def test_cli_writes_the_document_to_a_file(tmp_path, capsys):
    root = _archive(tmp_path)
    out = tmp_path / "out" / "attestation.md"
    code = main(
        [
            "--repo",
            str(root),
            "attest",
            "sat69b",
            "--rfc",
            "AAA080808HL8",
            "--on",
            "2026-09-07",
            "--output",
            str(out),
        ]
    )
    assert code == 0
    assert "wrote" in capsys.readouterr().out
    assert "Sentencia Favorable" in out.read_text(encoding="utf-8")


def test_cli_prints_to_stdout_without_output(tmp_path, capsys):
    root = _archive(tmp_path)
    code = main(
        ["--repo", str(root), "attest", "sat69b", "--rfc", "AAA080808HL8", "--on", "2026-09-07"]
    )
    assert code == 0
    assert "# Point-in-time attestation" in capsys.readouterr().out


def test_cli_refuses_a_feed_that_has_no_attestation_product(tmp_path, capsys):
    root = _archive(tmp_path)
    code = main(
        ["--repo", str(root), "attest", "catcfdi", "--rfc", "AAA080808HL8", "--on", "2026-09-07"]
    )
    assert code == 1
    assert "offered for 'sat69b' only" in capsys.readouterr().err


def test_cli_refuses_an_out_of_coverage_date(tmp_path, capsys):
    root = _archive(tmp_path)
    code = main(
        ["--repo", str(root), "attest", "sat69b", "--rfc", "AAA080808HL8", "--on", "2020-01-01"]
    )
    assert code == 1
    assert "before this archive begins" in capsys.readouterr().err


def test_the_real_archive_can_attest_its_own_coverage_start():
    """The committed sat69b snapshot answers for the day it was taken."""
    root = Path(__file__).resolve().parents[1]
    if not (root / "data" / FEED_ID).exists():  # pragma: no cover - fresh clone
        pytest.skip("no sat69b snapshot in this checkout")
    start, _ = coverage(root)
    text = attest("AAA080808HL8", root=root, on=start.isoformat())
    assert "Coverage begins %s" % start.isoformat() in text
    assert "Listado_Completo_69-B.csv" in text
