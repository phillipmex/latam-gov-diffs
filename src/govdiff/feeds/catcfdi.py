"""catCFDI - the SAT's CFDI 4.0 catalogues (Anexo 20).

Publisher: Servicio de Administracion Tributaria, Mexico.

One workbook, 28 sheets, ~46.5 MB of legacy `.xls`. Each sheet is a separate
catalogue (`c_ClaveProdServ`, `c_ClaveUnidad`, `c_CodigoPostal`, ...), and each
sheet carries two to five title and metadata rows above its real header row, so
the header has to be found by content rather than assumed to be row 0.

Storage shape: **one Parquet per version, with a leading `catalogo` column**,
not one Parquet per sheet. The snapshot layer already writes exactly one
`data.parquet` per version and the differ already reads exactly one frame per
side; a long frame keyed by `(catalogo, clave, ...)` therefore needs no change
at all to `snapshot.py`, `diff.py` or `runner.py`, while a file-per-sheet layout
would need a new directory convention, a new sidecar shape and a differ that
loops over tables. The composite key is what keeps the catalogues apart: code
`01` exists in `c_Exportacion`, `c_Periodicidad`, `c_Meses` and `c_ObjetoImp`,
and those four rows must never be compared with each other.

Every value is stored as text, for the same reason as the cClassTrib feed: the
same column arrives as a number in one release and a string in the next, and
codes such as `01010101` must not become integers.
"""

from __future__ import annotations

import html
import io
import re
import unicodedata
from datetime import date, datetime

import pandas as pd

from govdiff.errors import FeedError
from govdiff.fetch import fetch, make_session

FEED_ID = "catcfdi"
BASE_URL = "http://omawww.sat.gob.mx/tramitesyservicios/Paginas/"
LISTING_URL = BASE_URL + "anexo_20.htm"
DOCUMENT_URL = BASE_URL + "documentos/catCFDI_V_4_20260903.xls"

# Anchors on the Anexo 20 page that point at a dated catalogue workbook.
# Filenames seen: catCFDI_V_4_20260903.xls (YYYYMMDD, CFDI 4.0) and
# catCFDI_V_33_31032023.xls (DDMMYYYY, CFDI 3.3).
_CATALOGUE_HREF = re.compile(
    r"href=\"([^\"]*catCFDI_V_(\d+)_(\d{8})\.xlsx?)\"", re.I
)

# Back-version URLs that are live but are not linked from the Anexo 20 page.
# The page's two "Versiones anteriores" links are about the guias de llenado
# and the preguntas frecuentes, not the catalogues, and they lead to a second
# HTML landing page that this project does not scrape. This one URL was
# recorded by the day-0 probe and is verified on every bootstrap; a 404 is
# reported and the run continues.
KNOWN_BACK_VERSIONS = (BASE_URL + "documentos/catCFDI_V_4_20241204.xls",)

# Only CFDI 4.0 is in scope. 3.3 was retired for issuance in 2022 and its
# catalogue has not been republished since 2023.
IN_SCOPE_CFDI_VERSION = "4"

_WHITESPACE = re.compile(r"\s+")

# A cell that names a catalogue column: `c_ClaveProdServ`, `C_PatenteAduanal`.
_CODE_HEADER = re.compile(r"^c_[A-Za-z]", re.I)

# SAT splits its two largest catalogues over several sheets:
# `c_CodigoPostal_Parte_1`/`_Parte_2` and `C_Colonia_1`/`_2`/`_3`. They are one
# catalogue each - a postal code moving from part 1 to part 2 between releases
# is not a deletion plus an insertion - so the suffix is stripped and the parts
# are concatenated.
_SHEET_PART_SUFFIX = re.compile(r"(?:_parte)?_\d+$", re.I)

# How many rows from the top to search for the header row. The deepest header
# seen is row 5 (`c_FormaPago`, `c_MetodoPago`, `c_CodigoPostal_*`).
_HEADER_SEARCH_ROWS = 12

# Catalogues whose first `c_` column does not identify a row on its own.
# Values are the normalised column names that together do. Everything not
# listed here is keyed on its single `c_` column.
#
#   c_Colonia             colonia numbers restart inside every postal code
#   c_Localidad           locality numbers restart inside every state
#   c_Municipio           municipality numbers restart inside every state
#   c_NumPedimentoAduana  one row per customs office x broker patent x year
#   c_TasaOCuota          not a code table at all: its rows are tax rates, and
#                         the `c_TasaOCuota` column holds only the lower bound
#                         of a range and is empty on the 16 fixed-rate rows
_COMPOSITE_KEYS = {
    "c_Colonia": ("c_colonia", "c_codigopostal"),
    "c_Localidad": ("c_localidad", "c_estado"),
    "c_Municipio": ("c_municipio", "c_estado"),
    "c_NumPedimentoAduana": ("c_aduana", "patente", "ejercicio"),
    "c_TasaOCuota": ("rango_o_fijo", "impuesto", "valor_maximo"),
}

# The key columns of the long frame. Catalogues with a single-column key leave
# `clave_2` and `clave_3` empty.
KEY_FIELDS = ["catalogo", "clave", "clave_2", "clave_3"]
_MAX_KEY_PARTS = 3


# ---------------------------------------------------------------------------
# Cell and header normalisation
#
# Deliberately a local copy of the rules the cClassTrib adapter uses: the two
# feeds have to normalise identically for the diff output to read the same, and
# day 1's parser is left untouched.
# ---------------------------------------------------------------------------


def normalise_text(value: str) -> str:
    r"""Collapse every kind of whitespace the spreadsheet uses into single spaces.

    SAT cells mix newlines, NBSP and the zero-width space U+200B; `\s` covers
    the first two and the third is stripped separately.
    """
    return _WHITESPACE.sub(" ", value.replace("​", "")).strip()


def normalise_header(name: str) -> str:
    """`Fecha  inicio de vigencia` -> `fecha_inicio_de_vigencia`."""
    text = unicodedata.normalize("NFKD", normalise_text(str(name)))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = re.sub(r"[^0-9A-Za-z]+", "_", text).strip("_").lower()
    return text or "column"


def normalise_value(value) -> str | None:
    """One cell -> text, or None when empty."""
    if value is None:
        return None
    if isinstance(value, float) and pd.isna(value):
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    if isinstance(value, datetime):
        if value.hour or value.minute or value.second:
            return value.isoformat(sep=" ")
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    text = normalise_text(str(value))
    return text or None


def _unique_headers(labels: list[str]) -> list[str | None]:
    """Name the columns, dropping unnamed ones and de-duplicating repeats.

    `c_CodigoPostal` ships two columns both labelled
    `Dia_Inicio_Horario_Verano`; the second becomes `..._2`.
    """
    names: list[str | None] = []
    used: dict[str, int] = {}
    for label in labels:
        if not label:
            names.append(None)
            continue
        name = normalise_header(label)
        used[name] = used.get(name, 0) + 1
        if used[name] > 1:
            name = "%s_%d" % (name, used[name])
        names.append(name)
    return names


# ---------------------------------------------------------------------------
# Sheet parsing
# ---------------------------------------------------------------------------


def catalogue_name(sheet_name: str) -> str:
    """`C_Colonia_2` -> `c_Colonia`, `c_CodigoPostal_Parte_1` -> `c_CodigoPostal`.

    The `c_` prefix is lower-cased because SAT is inconsistent about it
    (`C_Colonia` but `c_ClaveUnidad`) and the catalogue name is half of the
    diff key, so it has to be stable across releases.
    """
    name = _SHEET_PART_SUFFIX.sub("", normalise_text(sheet_name))
    if name[:2].lower() == "c_":
        return "c_" + name[2:]
    return name


def _row_labels(frame: pd.DataFrame, row_index: int) -> list[str]:
    return [normalise_text(str(v)) if not pd.isna(v) else "" for v in frame.iloc[row_index]]


def find_header_row(frame: pd.DataFrame) -> int:
    """Index of the real header row of a catalogue sheet.

    Above it sit a title row, the `Version CFDI / Version catalogo / ...`
    metadata pair and one or more blank spacers, and their depth differs per
    sheet. The header is the first row that names at least one `c_` column and
    labels at least two columns in total.
    """
    for row_index in range(min(_HEADER_SEARCH_ROWS, len(frame))):
        labels = _row_labels(frame, row_index)
        if sum(1 for label in labels if label) < 2:
            continue
        if any(_CODE_HEADER.match(label) for label in labels):
            return row_index
    raise FeedError("no header row found in the first %d rows" % _HEADER_SEARCH_ROWS)


def _merge_subheader(labels: list[str], sub_labels: list[str]) -> list[str]:
    """Fold a second header line into the first.

    Four sheets spread their header over two rows: `c_UsoCFDI` puts
    `Fisica`/`Moral` under `Aplica para tipo persona`, `c_RegimenFiscal` does
    the same, `c_TasaOCuota` puts `Valor minimo`/`Valor maximo` under
    `c_TasaOCuota`, and `c_CodigoPostal` puts the time-zone detail columns
    under `Referencias del Huso Horario`.
    """
    merged = []
    for index, label in enumerate(labels):
        sub = sub_labels[index] if index < len(sub_labels) else ""
        if label and sub:
            merged.append("%s %s" % (label, sub))
        else:
            merged.append(label or sub)
    return merged


def _has_subheader(frame: pd.DataFrame, header_row: int) -> bool:
    """True when the row under the header continues it rather than starting data.

    The test is that its first cell is empty while other cells are filled. On
    every catalogue sheet the first column is either the code or, for
    `c_TasaOCuota`, `Rango o Fijo`, and both are populated on every data row.
    """
    if header_row + 1 >= len(frame):
        return False
    labels = _row_labels(frame, header_row + 1)
    return not labels[0] and any(labels)


def key_columns(catalogue: str, columns: list[str]) -> list[str]:
    """The columns that identify a row of this catalogue."""
    wanted = _COMPOSITE_KEYS.get(catalogue)
    if wanted:
        missing = [c for c in wanted if c not in columns]
        if missing:
            raise FeedError(
                "%s no longer has its key column(s) %s; columns are %s"
                % (catalogue, ", ".join(missing), ", ".join(columns))
            )
        return list(wanted)
    for column in columns:
        if _CODE_HEADER.match(column):
            return [column]
    return columns[:1]


def parse_sheet(frame: pd.DataFrame, catalogue: str) -> tuple[list[str], list[dict]]:
    """One raw sheet -> (column order, rows) with `catalogo`/`clave*` filled in."""
    header_row = find_header_row(frame)
    labels = _row_labels(frame, header_row)
    first_data_row = header_row + 1
    if _has_subheader(frame, header_row):
        labels = _merge_subheader(labels, _row_labels(frame, header_row + 1))
        first_data_row = header_row + 2

    names = _unique_headers(labels)
    keep = [i for i, name in enumerate(names) if name is not None]
    columns = [names[i] for i in keep]
    if not columns:
        raise FeedError("%s: the header row labels no columns" % catalogue)

    keys = key_columns(catalogue, columns)
    if len(keys) > _MAX_KEY_PARTS:
        raise FeedError(
            "%s needs a %d-part key but the frame carries %d"
            % (catalogue, len(keys), _MAX_KEY_PARTS)
        )
    key_positions = [columns.index(k) for k in keys]

    rows: list[dict] = []
    for values in frame.iloc[first_data_row:].itertuples(index=False, name=None):
        cells = [normalise_value(values[i]) if i < len(values) else None for i in keep]
        if not any(cells):
            continue
        key_parts = [cells[p] for p in key_positions]
        if not any(key_parts):
            # `c_TipoDeComprobante` carries one code-less row holding only the
            # `Valor maximo` limits; it identifies no comprobante type.
            continue
        record = {"catalogo": catalogue}
        for slot in range(_MAX_KEY_PARTS):
            name = "clave" if slot == 0 else "clave_%d" % (slot + 1)
            record[name] = key_parts[slot] if slot < len(key_parts) else None
        record.update(dict(zip(columns, cells)))
        rows.append(record)
    return columns, rows


def excel_engine(content: bytes) -> str:
    """`xlrd` for the legacy `.xls` SAT ships, `openpyxl` for a `.xlsx`.

    SAT has published this workbook as `.xls` since 2017, so xlrd is the live
    path; the sniff exists because the test fixtures are `.xlsx` (xlrd 2.x
    refuses that format outright) and because SAT could switch at any release.
    """
    if content.startswith(b"PK\x03\x04"):
        return "openpyxl"
    return "xlrd"


def parse(content: bytes) -> pd.DataFrame:
    """Parse the whole catalogue workbook into one long frame.

    The frame is `catalogo`, `clave`, `clave_2`, `clave_3`, then the union of
    every sheet's own columns in the order the sheets present them.
    """
    workbook = pd.ExcelFile(io.BytesIO(content), engine=excel_engine(content))
    try:
        ordered_columns: list[str] = []
        rows: list[dict] = []
        for sheet_name in workbook.sheet_names:
            catalogue = catalogue_name(sheet_name)
            sheet = workbook.parse(sheet_name, header=None, dtype=object)
            columns, sheet_rows = parse_sheet(sheet, catalogue)
            for column in columns:
                if column not in ordered_columns:
                    ordered_columns.append(column)
            rows.extend(sheet_rows)
    finally:
        workbook.close()

    if not rows:
        raise FeedError("the catalogue workbook parsed to zero rows")

    frame = pd.DataFrame(rows, columns=KEY_FIELDS + ordered_columns, dtype="string")
    return frame.reset_index(drop=True)


def sheet_inventory(content: bytes) -> list[dict]:
    """Per-sheet report: header row, key columns, row counts. Used by the log."""
    workbook = pd.ExcelFile(io.BytesIO(content), engine=excel_engine(content))
    try:
        inventory = []
        for sheet_name in workbook.sheet_names:
            catalogue = catalogue_name(sheet_name)
            sheet = workbook.parse(sheet_name, header=None, dtype=object)
            header_row = find_header_row(sheet)
            columns, rows = parse_sheet(sheet, catalogue)
            inventory.append(
                {
                    "sheet": sheet_name,
                    "catalogo": catalogue,
                    "header_row": header_row,
                    "subheader": _has_subheader(sheet, header_row),
                    "raw_rows": int(len(sheet)),
                    "rows": len(rows),
                    "columns": columns,
                    "key": key_columns(catalogue, columns),
                }
            )
    finally:
        workbook.close()
    return inventory


# ---------------------------------------------------------------------------
# Version discovery
# ---------------------------------------------------------------------------


def _date_from_filename(version: str, stamp: str) -> str:
    """`4`,`20260903` -> `2026-09-03`; `33`,`31032023` -> `2023-03-31`.

    CFDI 4.0 files are stamped YYYYMMDD and 3.3 files DDMMYYYY. The two are
    told apart by whether the first four digits are a plausible year.
    """
    if 2000 <= int(stamp[:4]) <= 2999:
        return "%s-%s-%s" % (stamp[:4], stamp[4:6], stamp[6:8])
    return "%s-%s-%s" % (stamp[4:8], stamp[2:4], stamp[:2])


def parse_listing(listing_html: str) -> list[dict]:
    """Every catCFDI workbook the Anexo 20 page links, oldest first.

    Includes the CFDI 3.3 workbook so the log can record it; callers filter on
    `cfdi_version`.
    """
    entries: dict[str, dict] = {}
    for match in _CATALOGUE_HREF.finditer(listing_html):
        href = html.unescape(match.group(1))
        url = href if href.lower().startswith("http") else BASE_URL + href.lstrip("/")
        iso = _date_from_filename(match.group(2), match.group(3))
        day, month, year = iso[8:10], iso[5:7], iso[:4]
        entries[url] = {
            "title": url.rsplit("/", 1)[-1],
            "cfdi_version": match.group(2),
            "date": iso,
            "published": "%s/%s/%s" % (day, month, year),
            "url": url,
            "linked": True,
        }
    return sorted(entries.values(), key=lambda e: (e["date"], e["url"]))


def list_versions(session=None, listing_html: str | None = None) -> list[dict]:
    """Every in-scope CFDI 4.0 workbook, oldest first.

    Fetches the Anexo 20 page exactly once per call and never any other HTML
    page. Pass `listing_html` to parse an already-downloaded page and make no
    request at all. The known back-version URLs are appended because the page
    does not link them.
    """
    if listing_html is None:
        session = session or make_session()
        result = fetch(LISTING_URL, session=session, conditional=False)
        listing_html = (result.content or b"").decode("utf-8", errors="replace")

    listed = parse_listing(listing_html)
    entries = {e["url"]: e for e in listed if e["cfdi_version"] == IN_SCOPE_CFDI_VERSION}
    for url in KNOWN_BACK_VERSIONS:
        if url in entries:
            continue
        match = _CATALOGUE_HREF.search('href="%s"' % url)
        if not match:
            raise FeedError("known back-version URL is not a catCFDI filename: %s" % url)
        iso = _date_from_filename(match.group(2), match.group(3))
        entries[url] = {
            "title": url.rsplit("/", 1)[-1],
            "cfdi_version": match.group(2),
            "date": iso,
            "published": "%s/%s/%s" % (iso[8:10], iso[5:7], iso[:4]),
            "url": url,
            "linked": False,
        }
    return sorted(entries.values(), key=lambda e: (e["date"], e["url"]))


def current_document(session=None, listing_html: str | None = None) -> dict:
    """The newest CFDI 4.0 workbook the Anexo 20 page links.

    `DOCUMENT_URL` is only the workbook that was current when this feed was
    registered; SAT gives every release its own dated filename, so the nightly
    run re-reads the page once to notice a new one.
    """
    entries = [e for e in list_versions(session=session, listing_html=listing_html) if e["linked"]]
    if not entries:
        raise FeedError("the Anexo 20 page links no CFDI 4.0 catalogue workbook")
    return entries[-1]
