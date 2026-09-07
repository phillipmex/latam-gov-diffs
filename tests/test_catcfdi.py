from pathlib import Path

import pandas as pd
import pytest

from govdiff.config import load_feeds
from govdiff.diff import diff_frames
from govdiff.errors import FeedError
from govdiff.feeds import catcfdi

FIXTURE = Path(__file__).parent / "fixtures" / "catcfdi_sample.xlsx"

# Trimmed from the real Anexo 20 page fetched on 2026-09-07: the current CFDI
# 4.0 workbook, the retired 3.3 one, and two neighbouring documents that must
# not be picked up.
LISTING_FRAGMENT = """
<td><a target="_blank" href="documentos/catCFDI_V_4_20260903.xls">Cat&aacute;logos</a></td>
<td><a target="_blank" href="documentos/Guia_llenado_CFDI_global.pdf">Gu&iacute;a</a></td>
<td><a target="_blank" href="http://www.sat.gob.mx/sitio_internet/cfd/catalogos/catCFDI.xsd">Cat&aacute;logo de datos (xsd)</a></td>
<td><a target="_blank" href="documentos/catCFDI_V_33_31032023.xls">Cat&aacute;logos CFDI Versi&oacute;n 3.3 (xls)</a></td>
"""


@pytest.fixture(scope="module")
def parsed():
    return catcfdi.parse(FIXTURE.read_bytes())


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------


def test_every_catalogue_sheet_is_parsed(parsed):
    assert parsed["catalogo"].unique().tolist() == [
        "c_Exportacion",
        "c_Periodicidad",
        "c_UsoCFDI",
    ]
    assert len(parsed) == 23


def test_frame_starts_with_the_key_columns(parsed):
    assert parsed.columns[:4].tolist() == catcfdi.KEY_FIELDS
    assert load_feeds(Path(__file__).parents[1] / "feeds.yaml")["catcfdi"].key_fields == (
        catcfdi.KEY_FIELDS
    )


def test_column_names_are_snake_case(parsed):
    assert "c_exportacion" in parsed.columns
    assert "fecha_inicio_de_vigencia" in parsed.columns
    assert "regimen_fiscal_receptor" in parsed.columns


def test_values_are_text_and_dates_are_iso(parsed):
    assert all(str(dtype) == "string" for dtype in parsed.dtypes)
    row = parsed[parsed["catalogo"].eq("c_Exportacion") & parsed["clave"].eq("04")].iloc[0]
    assert row["fecha_inicio_de_vigencia"] == "2022-02-25"
    # Codes keep their leading zero instead of becoming the integer 4.
    assert row["c_exportacion"] == "04"


def test_title_and_metadata_rows_are_not_data(parsed):
    assert "Versión CFDI" not in parsed["clave"].tolist()
    assert not parsed["clave"].str.startswith("Catálogo").any()


def test_unused_key_slots_are_empty(parsed):
    assert parsed["clave_2"].isna().all()
    assert parsed["clave_3"].isna().all()


# ---------------------------------------------------------------------------
# Header-row detection
# ---------------------------------------------------------------------------


def raw_sheet(rows):
    return pd.DataFrame(rows, dtype=object)


def test_header_row_is_found_below_the_title_and_metadata_rows():
    sheet = raw_sheet(
        [
            ["Catálogo de formas de pago.", None, None],
            ["Versión CFDI", "Versión catálogo", "Revisión catálogo"],
            [4.0, 1.0, 0.0],
            [None, None, None],
            [None, None, None],
            ["c_FormaPago", "Descripción", "Bancarizado"],
            ["01", "Efectivo", "No"],
        ]
    )
    assert catcfdi.find_header_row(sheet) == 5


def test_header_row_needs_a_c_prefixed_label():
    sheet = raw_sheet([["Clave", "Descripción"], ["01", "Efectivo"]])
    with pytest.raises(FeedError):
        catcfdi.find_header_row(sheet)


def test_a_single_labelled_cell_is_a_title_not_a_header():
    sheet = raw_sheet(
        [
            ["c_Moneda del catálogo", None, None],
            ["c_Moneda", "Descripción", "Decimales"],
            ["MXN", "Peso Mexicano", "2"],
        ]
    )
    assert catcfdi.find_header_row(sheet) == 1


def test_two_row_headers_are_merged(parsed):
    # c_UsoCFDI writes `Física`/`Moral` on a second header line under
    # `Aplica para tipo persona`; both must survive as columns.
    assert "aplica_para_tipo_persona_fisica" in parsed.columns
    assert "moral" in parsed.columns
    row = parsed[parsed["clave"].eq("D01")].iloc[0]
    assert row["aplica_para_tipo_persona_fisica"] == "Sí"
    assert row["moral"] == "No"


def test_sheet_inventory_reports_header_depth_and_keys():
    inventory = {row["sheet"]: row for row in catcfdi.sheet_inventory(FIXTURE.read_bytes())}
    assert inventory["c_UsoCFDI"]["header_row"] == 4
    assert inventory["c_UsoCFDI"]["subheader"] is True
    assert inventory["c_Exportacion"]["subheader"] is False
    assert inventory["c_Periodicidad"]["key"] == ["c_periodicidad"]


# ---------------------------------------------------------------------------
# Catalogue naming and key selection
# ---------------------------------------------------------------------------


def test_split_sheets_collapse_to_one_catalogue():
    assert catcfdi.catalogue_name("c_CodigoPostal_Parte_1") == "c_CodigoPostal"
    assert catcfdi.catalogue_name("c_CodigoPostal_Parte_2") == "c_CodigoPostal"
    assert catcfdi.catalogue_name("C_Colonia_3") == "c_Colonia"
    assert catcfdi.catalogue_name("c_ClaveProdServ") == "c_ClaveProdServ"


def test_key_defaults_to_the_first_c_column():
    assert catcfdi.key_columns("c_Moneda", ["c_moneda", "descripcion"]) == ["c_moneda"]


def test_catalogues_that_need_more_than_one_column_say_so():
    assert catcfdi.key_columns(
        "c_Colonia", ["c_colonia", "c_codigopostal", "nombre_del_asentamiento"]
    ) == ["c_colonia", "c_codigopostal"]
    assert catcfdi.key_columns(
        "c_NumPedimentoAduana", ["c_aduana", "patente", "ejercicio", "cantidad"]
    ) == ["c_aduana", "patente", "ejercicio"]


def test_a_vanished_key_column_is_loud():
    with pytest.raises(FeedError):
        catcfdi.key_columns("c_Colonia", ["c_colonia", "nombre_del_asentamiento"])


# ---------------------------------------------------------------------------
# Composite-key diffing
# ---------------------------------------------------------------------------


def frame(rows):
    return pd.DataFrame(rows, dtype="string")


def test_the_same_code_in_two_catalogues_does_not_collide():
    # `01` is a real code in both c_Exportacion and c_Periodicidad.
    before = frame(
        [
            {"catalogo": "c_Exportacion", "clave": "01", "clave_2": None, "clave_3": None,
             "descripcion": "No aplica"},
            {"catalogo": "c_Periodicidad", "clave": "01", "clave_2": None, "clave_3": None,
             "descripcion": "Diario"},
        ]
    )
    after = frame(
        [
            {"catalogo": "c_Exportacion", "clave": "01", "clave_2": None, "clave_3": None,
             "descripcion": "No aplica"},
            {"catalogo": "c_Periodicidad", "clave": "01", "clave_2": None, "clave_3": None,
             "descripcion": "Diaria"},
        ]
    )
    records, stats = diff_frames(before, after, catcfdi.KEY_FIELDS)
    assert (stats["added"], stats["removed"], stats["changed"], stats["unchanged"]) == (0, 0, 1, 1)
    assert records[0]["key"]["catalogo"] == "c_Periodicidad"
    assert records[0]["fields"] == {"descripcion": {"before": "Diario", "after": "Diaria"}}
    assert stats["duplicate_keys_from"] == 0


def test_the_same_code_in_two_catalogues_is_not_an_add_and_a_remove():
    before = frame(
        [{"catalogo": "c_Exportacion", "clave": "05", "clave_2": None, "clave_3": None,
          "descripcion": "Nueva"}]
    )
    after = frame(
        [{"catalogo": "c_Periodicidad", "clave": "05", "clave_2": None, "clave_3": None,
          "descripcion": "Bimestral"}]
    )
    _, stats = diff_frames(before, after, catcfdi.KEY_FIELDS)
    assert (stats["added"], stats["removed"], stats["changed"]) == (1, 1, 0)


def test_a_second_key_part_separates_rows_sharing_a_code():
    # Colonia 0001 exists inside thousands of postal codes.
    before = frame(
        [
            {"catalogo": "c_Colonia", "clave": "0001", "clave_2": "01000", "clave_3": None,
             "nombre_del_asentamiento": "San Ángel"},
            {"catalogo": "c_Colonia", "clave": "0001", "clave_2": "06000", "clave_3": None,
             "nombre_del_asentamiento": "Centro"},
        ]
    )
    after = frame(
        [
            {"catalogo": "c_Colonia", "clave": "0001", "clave_2": "01000", "clave_3": None,
             "nombre_del_asentamiento": "San Ángel"},
            {"catalogo": "c_Colonia", "clave": "0001", "clave_2": "06000", "clave_3": None,
             "nombre_del_asentamiento": "Centro Histórico"},
        ]
    )
    records, stats = diff_frames(before, after, catcfdi.KEY_FIELDS)
    assert (stats["added"], stats["removed"], stats["changed"], stats["unchanged"]) == (0, 0, 1, 1)
    assert records[0]["key"]["clave_2"] == "06000"


# ---------------------------------------------------------------------------
# Version discovery
# ---------------------------------------------------------------------------


def test_listing_yields_both_cfdi_versions():
    entries = catcfdi.parse_listing(LISTING_FRAGMENT)
    assert [(e["cfdi_version"], e["date"]) for e in entries] == [
        ("33", "2023-03-31"),
        ("4", "2026-09-03"),
    ]
    assert entries[1]["url"].endswith("Paginas/documentos/catCFDI_V_4_20260903.xls")


def test_only_cfdi_4_is_listed_and_back_versions_are_appended():
    entries = catcfdi.list_versions(listing_html=LISTING_FRAGMENT)
    assert [e["date"] for e in entries] == ["2024-12-04", "2026-09-03"]
    assert [e["linked"] for e in entries] == [False, True]
    assert all(e["cfdi_version"] == "4" for e in entries)


def test_current_document_is_the_newest_linked_workbook():
    current = catcfdi.current_document(listing_html=LISTING_FRAGMENT)
    assert current["date"] == "2026-09-03"
    assert current["published"] == "03/09/2026"


def test_a_page_without_a_cfdi_4_workbook_is_loud():
    with pytest.raises(FeedError):
        catcfdi.current_document(
            listing_html='<a href="documentos/catCFDI_V_33_31032023.xls">3.3</a>'
        )


def test_filename_dates_are_read_in_the_right_order():
    assert catcfdi._date_from_filename("4", "20260903") == "2026-09-03"
    assert catcfdi._date_from_filename("33", "31032023") == "2023-03-31"


def test_engine_follows_the_container_format():
    assert catcfdi.excel_engine(FIXTURE.read_bytes()) == "openpyxl"
    assert catcfdi.excel_engine(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1") == "xlrd"


def test_the_feed_is_registered_and_enabled():
    feed = load_feeds(Path(__file__).parents[1] / "feeds.yaml")["catcfdi"]
    assert feed.enabled
    assert feed.parser == "govdiff.feeds.catcfdi"
    assert feed.document_url == catcfdi.DOCUMENT_URL
    assert feed.listing_url == catcfdi.LISTING_URL
