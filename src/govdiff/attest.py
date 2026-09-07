"""Point-in-time attestations built from the archived `sat69b` snapshots.

SAT publishes one file, `Listado_Completo_69-B.csv`, and overwrites it. There
is no dated back-series and no way to ask SAT what the list said last March.
This repository keeps a dated snapshot of every version it has observed, so it
*can* answer that question - but only for the days it was actually watching.

`govdiff attest sat69b --rfc <RFC> --on <YYYY-MM-DD>` turns one of those
snapshots into a written statement: whether the RFC appeared, under which
`situacion`, with the oficio numbers and publication dates the list carried,
and the evidence that ties the answer to a specific file - version id, the
sha256 of the bytes SAT served, the document URL, and the `Last-Modified`
value SAT reported at the time.

Three rules decide what the document may say, and all three are printed in it:

**Coverage starts at the first archived snapshot.** Before that day this
archive holds nothing and no statement is possible. Asking for an earlier date
is an error with the coverage window in the message, never a guess.

**A snapshot's window runs to the next observation.** The archive knows the
list's content at the moments it fetched it. Version *i* is taken to describe
the published list from the day it was observed until the day the next version
was observed; that next observation is named in the document, so the reader can
see exactly where the evidence ends.

**Nothing is inferred about SAT's intent.** The document reports what the file
said. It is not legal advice and it is not a substitute for SAT's own
constancia.

There is no network access anywhere in this module.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path

from govdiff.errors import AttestationNotPossible
from govdiff.snapshot import feed_dir, list_versions, read_meta, read_version

# The attestation product covers this feed and only this feed. The other two
# publishers keep dated back-versions online, so a point-in-time statement
# about them is something anyone can reproduce from the publisher.
FEED_ID = "sat69b"

RFC_COLUMN = "rfc"
NAME_COLUMN = "nombre_del_contribuyente"
SITUACION_COLUMN = "situacion_del_contribuyente"

# (label, oficio column, publication column) in the order SAT writes them.
# Every stage a proceeding can have passed through, SAT-side and DOF-side.
STAGE_COLUMNS = (
    (
        "Presuncion - oficio global SAT",
        "numero_y_fecha_de_oficio_global_de_presuncion_sat",
        "publicacion_pagina_sat_presuntos",
    ),
    (
        "Presuncion - oficio global DOF",
        "numero_y_fecha_de_oficio_global_de_presuncion_dof",
        "publicacion_dof_presuntos",
    ),
    (
        "Desvirtuado - oficio global SAT",
        "numero_y_fecha_de_oficio_global_de_contribuyentes_que_desvirtuaron_sat",
        "publicacion_pagina_sat_desvirtuados",
    ),
    (
        "Desvirtuado - oficio global DOF",
        "numero_y_fecha_de_oficio_global_de_contribuyentes_que_desvirtuaron_dof",
        "publicacion_dof_desvirtuados",
    ),
    (
        "Definitivo - oficio global SAT",
        "numero_y_fecha_de_oficio_global_de_definitivos_sat",
        "publicacion_pagina_sat_definitivos",
    ),
    (
        "Definitivo - oficio global DOF",
        "numero_y_fecha_de_oficio_global_de_definitivos_dof",
        "publicacion_dof_definitivos",
    ),
    (
        "Sentencia favorable - oficio global SAT",
        "numero_y_fecha_de_oficio_global_de_sentencia_favorable_sat",
        "publicacion_pagina_sat_sentencia_favorable",
    ),
    (
        "Sentencia favorable - oficio global DOF",
        "numero_y_fecha_de_oficio_global_de_sentencia_favorable_dof",
        "publicacion_dof_sentencia_favorable",
    ),
)

DISCLAIMER = (
    "This document reports what an archived copy of a public SAT file said on a "
    "given date. It is **not legal advice**, it is **not a substitute for SAT's own "
    "constancia** or for a query against SAT's live service, and it does not state "
    "anything about the validity of any invoice or contract. It is evidence of what "
    "was published, and nothing more."
)


@dataclass(frozen=True)
class Observation:
    """One archived snapshot of the 69-B list, with its provenance."""

    version_id: str
    fetched_at: str
    observed_on: date
    sha256: str
    source_url: str
    last_modified: str | None
    row_count: int
    parquet: str
    parquet_bytes: int


def normalise_rfc(value: str) -> str:
    """RFCs are compared upper-case with spaces and hyphens removed."""
    return "".join(ch for ch in str(value).upper() if ch.isalnum())


def parse_day(value: str | date) -> date:
    if isinstance(value, date):
        return value
    text = str(value).strip()
    try:
        return date.fromisoformat(text)
    except ValueError:
        raise AttestationNotPossible(
            "'%s' is not a date. Use YYYY-MM-DD." % text
        ) from None


def _day_of(timestamp: str) -> date:
    return datetime.fromisoformat(str(timestamp).replace("Z", "+00:00")).date()


def _cell(value) -> str:
    """A stored cell as plain text; missing and NA both become ''."""
    if value is None:
        return ""
    text = str(value)
    if text in ("nan", "None", "<NA>", "NaT"):
        return ""
    return text.strip()


def observations(root: Path) -> list[Observation]:
    """Every archived snapshot of the feed, oldest first."""
    out: list[Observation] = []
    for version in list_versions(FEED_ID, root):
        meta = read_meta(FEED_ID, version, root)
        parquet = feed_dir(FEED_ID, root) / version / "data.parquet"
        fetched_at = meta.get("fetched_at") or ""
        out.append(
            Observation(
                version_id=version,
                fetched_at=fetched_at,
                observed_on=_day_of(fetched_at) if fetched_at else date.fromisoformat(version[:10]),
                sha256=meta.get("sha256") or "",
                source_url=meta.get("source_url") or "",
                last_modified=meta.get("last_modified"),
                row_count=int(meta.get("row_count") or 0),
                parquet="data/%s/%s/data.parquet" % (FEED_ID, version),
                parquet_bytes=parquet.stat().st_size if parquet.exists() else 0,
            )
        )
    out.sort(key=lambda o: (o.observed_on, o.version_id))
    return out


def observed_through(root: Path, obs: list[Observation] | None = None) -> date:
    """The last day the archive is known to have looked at the source.

    A nightly run that finds the file unchanged writes no new version but does
    stamp `.state/<feed>.json`, so that file - not the newest snapshot - is the
    honest end of the coverage window.
    """
    obs = obs if obs is not None else observations(root)
    if not obs:
        raise AttestationNotPossible(
            "no %s snapshot is archived here, so no date can be attested." % FEED_ID
        )
    end = obs[-1].observed_on
    state_path = Path(root) / ".state" / ("%s.json" % FEED_ID)
    if state_path.is_file():
        try:
            with open(state_path, "r", encoding="utf-8") as fh:
                stamp = json.load(fh).get("last_fetched_at")
            if stamp:
                end = max(end, _day_of(stamp))
        except (ValueError, OSError):  # pragma: no cover - unreadable state file
            pass
    return end


def coverage(root: Path, obs: list[Observation] | None = None) -> tuple[date, date]:
    """First and last day this archive can speak about."""
    obs = obs if obs is not None else observations(root)
    if not obs:
        raise AttestationNotPossible(
            "no %s snapshot is archived here, so no date can be attested." % FEED_ID
        )
    return obs[0].observed_on, observed_through(root, obs)


def _out_of_coverage(day: date, start: date, end: date) -> AttestationNotPossible:
    if day < start:
        return AttestationNotPossible(
            "%s is before this archive begins. The first snapshot of the SAT 69-B list "
            "was taken on %s; SAT keeps no dated back-series, so no statement about an "
            "earlier date can be made from this archive or from anywhere else."
            % (day.isoformat(), start.isoformat())
        )
    return AttestationNotPossible(
        "%s is after the last day this archive observed the list (%s). Wait for the "
        "nightly run to cover it." % (day.isoformat(), end.isoformat())
    )


def in_force(day: date, obs: list[Observation]) -> tuple[Observation, list[Observation]]:
    """The snapshot describing the list on `day`, plus any others seen that day.

    When the list was observed more than once on the same day - a republication
    caught by two runs - the statement describes the last observation of that
    day and the others are named in the document.
    """
    seen = [o for o in obs if o.observed_on <= day]
    same_day = [o for o in seen if o.observed_on == day]
    return seen[-1], same_day[:-1]


def next_observation(day: date, obs: list[Observation]) -> Observation | None:
    later = [o for o in obs if o.observed_on > day]
    return later[0] if later else None


def records_for(rfc: str, observation: Observation, root: Path) -> list[dict]:
    """Every row of that snapshot whose RFC matches, in stored order."""
    frame = read_version(FEED_ID, observation.version_id, root)
    wanted = normalise_rfc(rfc)
    out: list[dict] = []
    if RFC_COLUMN not in frame.columns:  # pragma: no cover - schema guard
        raise AttestationNotPossible(
            "snapshot %s has no '%s' column." % (observation.version_id, RFC_COLUMN)
        )
    # Narrow first: the real list is 14,000 rows wide of 27 string columns, and
    # walking all of them per attestation is needless work.
    matches = frame[frame[RFC_COLUMN].map(lambda v: normalise_rfc(_cell(v)) == wanted)]
    for _, row in matches.iterrows():
        stages = []
        for label, oficio_col, pub_col in STAGE_COLUMNS:
            oficio = _cell(row.get(oficio_col)) if oficio_col in frame.columns else ""
            published = _cell(row.get(pub_col)) if pub_col in frame.columns else ""
            if not oficio and not published:
                continue
            iso_col = pub_col + "_iso"
            stages.append(
                {
                    "stage": label,
                    "oficio": oficio,
                    "published": published,
                    "published_iso": (
                        _cell(row.get(iso_col)) if iso_col in frame.columns else ""
                    ),
                }
            )
        out.append(
            {
                "rfc": _cell(row.get(RFC_COLUMN)),
                "name": _cell(row.get(NAME_COLUMN)) if NAME_COLUMN in frame.columns else "",
                "situacion": (
                    _cell(row.get(SITUACION_COLUMN)) if SITUACION_COLUMN in frame.columns else ""
                ),
                "stages": stages,
            }
        )
    return out


def _segment(rfc: str, observation: Observation, root: Path, window: dict) -> dict:
    records = records_for(rfc, observation, root)
    return {
        "observation": observation,
        "window": window,
        "found": bool(records),
        "situaciones": sorted({r["situacion"] for r in records if r["situacion"]}),
        "records": records,
    }


def build_attestation(
    rfc: str,
    *,
    root: Path,
    on: str | date | None = None,
    between: tuple[str | date, str | date] | None = None,
    generated_at: str | None = None,
) -> dict:
    """Assemble the statement. Reads the archive only; makes no request."""
    if (on is None) == (between is None):
        raise AttestationNotPossible("give exactly one of --on DATE or --between A B.")

    obs = observations(root)
    start, end = coverage(root, obs)
    subject = normalise_rfc(rfc)
    if not subject:
        raise AttestationNotPossible("--rfc needs an RFC, for example XAXX010101000.")

    if on is not None:
        days = [parse_day(on)]
    else:
        first, last = parse_day(between[0]), parse_day(between[1])
        if last < first:
            raise AttestationNotPossible(
                "--between wants the earlier date first (%s comes after %s)."
                % (first.isoformat(), last.isoformat())
            )
        days = [first, last]

    for day in days:
        if day < start or day > end:
            raise _out_of_coverage(day, start, end)

    if on is not None:
        held, also_same_day = in_force(days[0], obs)
        following = next_observation(days[0], obs)
        window = {
            "from": held.observed_on.isoformat(),
            "to": (
                (following.observed_on.isoformat() + " (exclusive)")
                if following
                else end.isoformat()
            ),
            "next_observation": following.fetched_at if following else None,
            "next_version_id": following.version_id if following else None,
            "also_observed_same_day": [o.version_id for o in also_same_day],
        }
        segments = [_segment(rfc, held, root, window)]
    else:
        first, last = days
        covering = [o for o in obs if o.observed_on <= last]
        # Every snapshot whose window touches the span: the one in force at the
        # start, plus every one observed inside it.
        held, _ = in_force(first, obs)
        chosen = [held] + [o for o in covering if first < o.observed_on <= last]
        segments = []
        for i, observation in enumerate(chosen):
            following = chosen[i + 1] if i + 1 < len(chosen) else next_observation(last, obs)
            segments.append(
                _segment(
                    rfc,
                    observation,
                    root,
                    {
                        "from": max(observation.observed_on, first).isoformat(),
                        "to": (
                            (following.observed_on.isoformat() + " (exclusive)")
                            if following and following.observed_on <= last
                            else last.isoformat()
                        ),
                        "next_observation": following.fetched_at if following else None,
                        "next_version_id": following.version_id if following else None,
                        "also_observed_same_day": [],
                    },
                )
            )

    return {
        "feed": FEED_ID,
        "rfc": subject,
        "rfc_as_given": str(rfc).strip(),
        "question": "on" if on is not None else "between",
        "on": days[0].isoformat() if on is not None else None,
        "between": [days[0].isoformat(), days[-1].isoformat()] if between else None,
        "coverage_start": start.isoformat(),
        "coverage_end": end.isoformat(),
        "generated_at": generated_at or datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "segments": segments,
    }


def _fmt_int(value: int) -> str:
    return "{:,}".format(int(value))


def _answer_line(report: dict) -> str:
    hits = [s for s in report["segments"] if s["found"]]
    if report["question"] == "on":
        segment = report["segments"][0]
        if not segment["found"]:
            return (
                "**No.** The RFC `%s` did not appear anywhere in the SAT 69-B list as "
                "published on %s." % (report["rfc"], report["on"])
            )
        situaciones = ", ".join(segment["situaciones"]) or "(no situacion recorded)"
        return "**Yes.** On %s the RFC `%s` appeared in %d proceeding(s), situacion: %s." % (
            report["on"],
            report["rfc"],
            len(segment["records"]),
            situaciones,
        )
    span = "%s and %s" % (report["between"][0], report["between"][1])
    if not hits:
        return "**No.** The RFC `%s` did not appear in any list published between %s." % (
            report["rfc"],
            span,
        )
    states = []
    for segment in report["segments"]:
        for value in segment["situaciones"]:
            if value not in states:
                states.append(value)
    if len(hits) == len(report["segments"]) and len(states) <= 1:
        return "**Yes, throughout.** Between %s the RFC `%s` appeared in every list this " % (
            span,
            report["rfc"],
        ) + "archive observed, situacion: %s." % (states[0] if states else "(none recorded)")
    return (
        "**Yes, in part.** Between %s the RFC `%s` appeared in %d of the %d lists this "
        "archive observed. Situaciones seen, in order: %s."
        % (span, report["rfc"], len(hits), len(report["segments"]), ", ".join(states) or "none")
    )


def render_markdown(report: dict) -> str:
    """The deliverable: one Markdown document, printable to PDF as it is."""
    lines: list[str] = []
    add = lines.append

    add("# Point-in-time attestation - SAT listado 69-B")
    add("")
    add("| | |")
    add("|---|---|")
    add("| Subject RFC | `%s` |" % report["rfc"])
    if report["question"] == "on":
        add("| Question | Did this RFC appear on the list published on %s? |" % report["on"])
    else:
        add(
            "| Question | Did this RFC appear on the lists published between %s and %s? |"
            % (report["between"][0], report["between"][1])
        )
    add("| Source | SAT, *Listado completo de contribuyentes (Articulo 69-B del CFF)* |")
    add("| Archive coverage | %s to %s |" % (report["coverage_start"], report["coverage_end"]))
    add("| Issued | %s |" % report["generated_at"])
    add("| Issued by | the latam-gov-diffs maintainers |")
    add("")
    add("## Statement")
    add("")
    add(_answer_line(report))
    add("")

    for number, segment in enumerate(report["segments"], start=1):
        observation = segment["observation"]
        window = segment["window"]
        heading = "## Evidence"
        if len(report["segments"]) > 1:
            heading = "## Evidence %d of %d - snapshot %s" % (
                number,
                len(report["segments"]),
                observation.version_id,
            )
        add(heading)
        add("")
        add("| field | value |")
        add("|---|---|")
        add("| Snapshot version id | `%s` |" % observation.version_id)
        add("| sha256 of the file SAT served | `%s` |" % observation.sha256)
        add("| SAT document URL | %s |" % observation.source_url)
        add(
            "| `Last-Modified` reported by SAT | %s |"
            % (observation.last_modified or "(not sent)")
        )
        add("| Observed (fetched) at | %s |" % observation.fetched_at)
        add("| Rows in that list | %s |" % _fmt_int(observation.row_count))
        add(
            "| Stored snapshot | `%s` (%s bytes) |"
            % (observation.parquet, _fmt_int(observation.parquet_bytes))
        )
        add("| Statement covers | %s to %s |" % (window["from"], window["to"]))
        if window["next_observation"]:
            add(
                "| Next observation | %s, snapshot `%s` |"
                % (window["next_observation"], window["next_version_id"])
            )
        else:
            add("| Next observation | none yet; this is the newest snapshot |")
        if window["also_observed_same_day"]:
            add(
                "| Also observed that day | %s (this statement describes the last "
                "observation of the day) |" % ", ".join(window["also_observed_same_day"])
            )
        add("")

        if not segment["found"]:
            add(
                "The RFC does not appear in this snapshot. All %s rows were searched on the "
                "`rfc` column, compared upper-case with punctuation removed."
                % _fmt_int(observation.row_count)
            )
            add("")
            continue

        for index, record in enumerate(segment["records"], start=1):
            title = "### Record %d of %d" % (index, len(segment["records"]))
            add(title)
            add("")
            add("- **RFC:** `%s`" % record["rfc"])
            add("- **Nombre del contribuyente:** %s" % (record["name"] or "(blank)"))
            add("- **Situacion del contribuyente:** **%s**" % (record["situacion"] or "(blank)"))
            add("")
            add("| stage | oficio | publication date (as SAT wrote it) | ISO |")
            add("|---|---|---|---|")
            for stage in record["stages"]:
                add(
                    "| %s | %s | %s | %s |"
                    % (
                        stage["stage"],
                        stage["oficio"] or "-",
                        stage["published"] or "-",
                        stage["published_iso"] or "-",
                    )
                )
            add("")

    add("## What this archive can and cannot reach")
    add("")
    add(
        "SAT publishes the 69-B list as a single file that is overwritten in place. There is "
        "no dated back-series, no versioned URL and no public history, so a statement about "
        "any day can only be made by somebody who took a copy on that day."
    )
    add("")
    add(
        "- **Coverage begins %s**, the day this archive took its first snapshot. No date "
        "before that can be attested here, and it cannot be recovered from SAT either."
        % report["coverage_start"]
    )
    add(
        "- **Coverage ends %s**, the last day the archive observed the source."
        % report["coverage_end"]
    )
    add(
        "- Between two observations the list is taken to be unchanged. Each evidence block "
        "names the next observation, so the exact edge of the evidence is visible."
    )
    add(
        "- 91 rows in the published list have their RFC suppressed to `XXXXXXXXXXXX` by court "
        "order. A search for a real RFC never matches those rows."
    )
    add("")
    add("## Reproducing this document")
    add("")
    add("```")
    if report["question"] == "on":
        add("govdiff attest sat69b --rfc %s --on %s" % (report["rfc"], report["on"]))
    else:
        add(
            "govdiff attest sat69b --rfc %s --between %s %s"
            % (report["rfc"], report["between"][0], report["between"][1])
        )
    add("```")
    add("")
    add(
        "Run against a clone of the archive, the command reads the stored snapshots and "
        "rebuilds this document. It makes no network request."
    )
    add("")
    add("## Disclaimer")
    add("")
    add(DISCLAIMER)
    add("")
    return "\n".join(lines)


def attest(
    rfc: str,
    *,
    root: Path,
    on: str | date | None = None,
    between: tuple[str | date, str | date] | None = None,
    generated_at: str | None = None,
) -> str:
    """Build and render in one call."""
    return render_markdown(
        build_attestation(rfc, root=root, on=on, between=between, generated_at=generated_at)
    )
