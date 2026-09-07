"""sat69b - the SAT's "listado completo 69-B" (Mexico).

Publisher: Servicio de Administracion Tributaria, Mexico.

Article 69-B of the Codigo Fiscal de la Federacion lets SAT publish taxpayers
it presumes issued invoices for operations that never happened. A taxpayer
enters the list as `Presunto`, and then moves to `Desvirtuado` (they rebutted
it), `Definitivo` (they did not), or `Sentencia Favorable` (a court overturned
it). The list is one CSV of about 14,000 rows.

**This is the one feed with no public back-series.** SAT keeps only the current
`Listado_Completo_69-B.csv` and organises the underlying pages by legal
category, not by date, so there is nothing to bootstrap and every day not
archived is lost for good. `run` is the whole feed.

Three things about the file that the parser has to deal with:

* it is **cp1252**, not UTF-8 and not latin-1 - see `detect_encoding`;
* two title rows sit above the real header row, so the header is found by
  content;
* the `No` column is a presentation ordinal, not data, and is dropped.
"""

from __future__ import annotations

import csv
import io
import re
import unicodedata
from datetime import datetime

import pandas as pd

from govdiff.errors import FeedError

FEED_ID = "sat69b"
DOCUMENT_URL = "http://omawww.sat.gob.mx/cifras_sat/Documents/Listado_Completo_69-B.csv"

# The publisher keeps no index page, no dated archive and no back-versions, so
# there is no listing URL and nothing this adapter can discover.
LISTING_URL = None

# SAT's SharePoint front end does send an ETag, but it is the document GUID
# plus a version counter that moves whenever any metadata is touched, so it
# says nothing about the bytes. The change signal for this feed is
# `Last-Modified` plus the sha256 of the body, and `run_feed` reads this flag
# to leave `If-None-Match` off the conditional request. Both validators are
# still recorded in `.state/sat69b.json` and in the version sidecar.
USE_ETAG = False

# How many lines from the top to search for the header row. Two title rows sit
# above it today; the allowance is generous because SAT edits that preamble.
HEADER_SEARCH_LINES = 20

# The header row is the one that names the taxpayer id column.
_HEADER_MARKER = "rfc"
_MIN_HEADER_LABELS = 3

# A presentation ordinal, renumbered 1..N on every publication. Keeping it
# would make one taxpayer inserted alphabetically near the top read as a change
# on every row below it, so the column is dropped rather than diffed.
_DROPPED_COLUMNS = ("no",)

# Dates are published as dd/mm/yyyy. Some cells instead hold two dates joined
# by " - " (a taxpayer that went through two separate proceedings) and two
# cells hold a raw Excel serial number that SAT never formatted. Only a bare
# dd/mm/yyyy is unambiguous, so only that gets an ISO sibling.
_DATE_COLUMN_PREFIX = "publicacion_"
_ISO_SUFFIX = "_iso"
_DDMMYYYY = re.compile(r"^(\d{2})/(\d{2})/(\d{4})$")

# The redaction placeholder. 91 rows carry it: SAT suppressed the taxpayer's
# identity by court order and wrote the reason into the name column.
SUPPRESSED_RFC = "XXXXXXXXXXXX"

# Rows are one 69-B proceeding against one taxpayer.
#
# The RFC alone is not a key: 82 RFCs repeat, 261 rows in all. Two different
# reasons, and they need different treatment.
#
#   * A taxpayer can be presumed twice, years apart, in two unrelated
#     proceedings. Both rows can end up `Definitivo`, so RFC + situacion does
#     not separate them either (66 rows still collide). What does separate them
#     is the presumption oficio - the document number that opened the
#     proceeding - which is filled on all 14,234 rows and never repeats for one
#     RFC. RFC + presumption oficio is unique across all 14,143 rows that carry
#     a real RFC.
#   * The situacion is deliberately NOT part of the key. A taxpayer moving
#     Presunto -> Definitivo -> Sentencia Favorable is the whole point of this
#     feed, and it has to read as a change to one record, not as a deletion
#     plus an insertion.
KEY_FIELDS = ["rfc", "numero_y_fecha_de_oficio_global_de_presuncion_sat"]

_WHITESPACE = re.compile(r"\s+")


# ---------------------------------------------------------------------------
# Cell and header normalisation
#
# Deliberately a local copy of the rules the other two adapters use: the feeds
# have to normalise identically for the diff output to read the same, and the
# earlier parsers are left untouched.
# ---------------------------------------------------------------------------


def normalise_text(value: str) -> str:
    r"""Collapse every kind of whitespace into single spaces.

    SAT cells carry trailing spaces, NBSP (0xA0 in cp1252) and the occasional
    embedded newline inside a quoted field.
    """
    return _WHITESPACE.sub(" ", value.replace("​", "").replace("\xa0", " ")).strip()


def normalise_header(name: str) -> str:
    """`Situacion del contribuyente` -> `situacion_del_contribuyente`."""
    text = unicodedata.normalize("NFKD", normalise_text(str(name)))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = re.sub(r"[^0-9A-Za-z]+", "_", text).strip("_").lower()
    return text or "column"


def normalise_value(value) -> str | None:
    """One cell -> text, or None when empty."""
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    return normalise_text(str(value)) or None


def _unique_headers(labels: list[str]) -> list[str]:
    names: list[str] = []
    used: dict[str, int] = {}
    for index, label in enumerate(labels):
        name = normalise_header(label) if label else "column_%d" % (index + 1)
        used[name] = used.get(name, 0) + 1
        if used[name] > 1:
            name = "%s_%d" % (name, used[name])
        names.append(name)
    return names


# ---------------------------------------------------------------------------
# Encoding and header detection
# ---------------------------------------------------------------------------


def detect_encoding(content: bytes) -> str:
    """Name the encoding this file actually uses, by inspecting the bytes.

    The response says `application/octet-stream` and carries no charset, and
    the file has no byte-order mark, so the bytes are the only evidence.

    The 2026-01-22 file decodes as UTF-8 nowhere and contains 0x92, 0x93, 0x94
    and 0x96 - a right single quote, both curly double quotes and an en dash in
    **cp1252**. In latin-1 those four bytes are unprintable C1 control
    characters, so latin-1 would decode without complaining and silently
    corrupt the text. That is the whole reason this function exists rather than
    a hard-coded "latin-1".
    """
    for encoding in ("utf-8-sig", "utf-8"):
        try:
            content.decode(encoding)
            return encoding
        except UnicodeDecodeError:
            pass
    # Not UTF-8. The two single-byte encodings SAT uses differ only in
    # 0x80-0x9F: cp1252 puts printable punctuation there, latin-1 puts C1
    # controls. A file that uses that range is cp1252.
    if any(0x80 <= byte <= 0x9F for byte in content):
        return "cp1252"
    return "latin-1"


def find_header_row(lines: list[str]) -> int:
    """Index of the real header line; the rows above it are the SAT preamble.

    Today line 0 is a legal notice about electronic signatures and line 1 is
    the list's own title, both padded out with empty commas to the full column
    count. The header is the first line that parses to at least three labelled
    fields, one of which is named `RFC`.
    """
    for index, line in enumerate(lines[:HEADER_SEARCH_LINES]):
        fields = next(csv.reader([line]), [])
        labels = [normalise_header(f) for f in fields if normalise_text(f)]
        if len(labels) < _MIN_HEADER_LABELS:
            continue
        if _HEADER_MARKER in labels:
            return index
    raise FeedError(
        "no 69-B header row (a row naming an RFC column) in the first %d lines"
        % HEADER_SEARCH_LINES
    )


def preamble(content: bytes, limit: int = HEADER_SEARCH_LINES) -> list[str]:
    """The lines above the header row, for the build log and for inspection."""
    text = content.decode(detect_encoding(content))
    lines = text.splitlines()
    return lines[: find_header_row(lines)][:limit]


# ---------------------------------------------------------------------------
# Dates
# ---------------------------------------------------------------------------


def iso_date(value: str | None) -> str | None:
    """`01/06/2018` -> `2018-06-01`. Anything else -> None.

    Day-first is not a guess: `25/05/2022` and `30/09/2016` appear throughout,
    so the first component cannot be a month. A cell holding two dates
    (`25/05/2022 - 26/04/2021`, 158 of them) or an unformatted Excel serial
    (`44014`, 2 of them) has no single unambiguous date and gets no sibling.
    """
    if not value:
        return None
    match = _DDMMYYYY.match(value)
    if not match:
        return None
    day, month, year = (int(part) for part in match.groups())
    try:
        return datetime(year, month, day).date().isoformat()
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------


def parse(content: bytes) -> pd.DataFrame:
    """The 69-B CSV -> one frame of text columns.

    Every value is stored as text, for the same reason as the other two feeds:
    an RFC, an oficio number and a folio must never become integers.
    """
    encoding = detect_encoding(content)
    lines = content.decode(encoding).splitlines()
    header_row = find_header_row(lines)

    raw = pd.read_csv(
        io.BytesIO(content),
        encoding=encoding,
        skiprows=header_row,
        dtype=str,
        keep_default_na=False,
    )
    raw.columns = _unique_headers([str(c) for c in raw.columns])

    columns = [c for c in raw.columns if c not in _DROPPED_COLUMNS]
    if not columns:
        raise FeedError("the 69-B header row labels no columns worth keeping")
    missing = [f for f in KEY_FIELDS if f not in columns]
    if missing:
        raise FeedError(
            "69-B no longer has its key column(s) %s; columns are %s"
            % (", ".join(missing), ", ".join(columns))
        )

    ordered: list[str] = []
    data: dict[str, list] = {}
    for column in columns:
        values = [normalise_value(v) for v in raw[column]]
        ordered.append(column)
        data[column] = values
        # An ISO sibling sits directly beside the source column it came from,
        # and the source string is always kept exactly as published.
        if column.startswith(_DATE_COLUMN_PREFIX):
            sibling = column + _ISO_SUFFIX
            ordered.append(sibling)
            data[sibling] = [iso_date(v) for v in values]

    frame = pd.DataFrame(data, columns=ordered, dtype="string")
    frame = frame[frame["rfc"].notna()].reset_index(drop=True)
    if frame.empty:
        raise FeedError("the 69-B CSV parsed to zero rows")
    return frame


def situacion_counts(frame: pd.DataFrame) -> dict[str, int]:
    """Rows per `situacion del contribuyente`, commonest first. Used by the log."""
    counts = frame["situacion_del_contribuyente"].value_counts(dropna=False)
    return {str(k): int(v) for k, v in counts.items()}


# ---------------------------------------------------------------------------
# Version discovery
# ---------------------------------------------------------------------------


def list_versions(session=None) -> list[dict]:
    """The one document that exists, and no request to find it.

    There is no listing page, no dated archive and no back-version URL for this
    feed - that absence is the reason the feed is worth running at all. The
    entry carries no date because the publisher's own date arrives only in the
    `Last-Modified` header of the response, which `run_feed` already uses as
    the version date.
    """
    return [
        {
            "title": DOCUMENT_URL.rsplit("/", 1)[-1],
            "date": None,
            "published": None,
            "url": DOCUMENT_URL,
            "linked": True,
        }
    ]
