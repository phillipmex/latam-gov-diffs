from pathlib import Path

import pytest

from govdiff.config import load_feeds
from govdiff.errors import FeedError
from govdiff.feeds import cclasstrib

FIXTURE = Path(__file__).parent / "fixtures" / "cclasstrib_sample.xlsx"

# Trimmed from the real listing page fetched on 2026-09-07. Two cClassTrib
# releases plus one neighbouring table that must not be picked up.
LISTING_FRAGMENT = """
<p><a target="_blank" href="exibirArquivo.aspx?conteudo=LeNQXfyYngg=">
<span class="tituloConteudo">Tabela de C&oacute;digo de Classifica&ccedil;&atilde;o Tribut&aacute;ria do IBS/CBS - Publicada em 15/12/2025</span></a><br />
Tabela de c&oacute;digos de classifica&ccedil;&atilde;o tribut&aacute;ria e indicadores de CST do IBS e CBS (cClassTrib)<br /></p>
<p><a target="_blank" href="exibirArquivo.aspx?conteudo=D5b4Ov84WDg=">
<span class="tituloConteudo">Tabela de Classifica&ccedil;&atilde;o Tribut&aacute;ria do IBS e CBS - Publicada em 23/06/2026</span></a><br />
Tabela de classifica&ccedil;&atilde;o tribut&aacute;ria do IBS e CBS (cClassTrib)<br /></p>
<p><a target="_blank" href="exibirArquivo.aspx?conteudo=IkC vAeU2Bs=">
<span class="tituloConteudo">Tabela de C&oacute;digo de &Iacute;ndice de Biocombust&iacute;vel do IBS e CBS - Publicada em 18/06/2026</span></a><br />
Tabela de c&oacute;digos de &iacute;ndice de biocombust&iacute;vel<br /></p>
"""


@pytest.fixture(scope="module")
def parsed():
    return cclasstrib.parse(FIXTURE.read_bytes())


def test_parses_one_row_per_classification_code(parsed):
    assert len(parsed) == 20
    assert parsed["cclasstrib"].is_unique


def test_column_names_are_snake_case(parsed):
    assert parsed.columns[:5].tolist() == [
        "cst_ibs_cbs",
        "descricao_cst_ibs_cbs",
        "cclasstrib",
        "nome_cclasstrib",
        "descricao_cclasstrib",
    ]
    assert all(name == name.lower() for name in parsed.columns)
    assert all(name.replace("_", "").isalnum() for name in parsed.columns)


def test_codes_stay_strings_with_their_leading_zeros(parsed):
    assert parsed["cclasstrib"].dtype == "string"
    assert parsed["cclasstrib"].iloc[0] == "000001"
    assert parsed["cst_ibs_cbs"].iloc[0] == "000"


def test_every_source_column_is_kept(parsed):
    # The 2025-12-12 release ships 37 named columns on the cClass sheet.
    assert len(parsed.columns) == 37
    assert "link" in parsed.columns
    assert "dataatualizacao" in parsed.columns


def test_whitespace_inside_cells_is_normalised(parsed):
    # The source puts newlines, U+2028 line separators, NBSP and runs of
    # spaces inside the legal-text cells; all of it collapses to one space.
    for value in parsed["lc_redacao"].dropna():
        assert "\n" not in value
        assert " " not in value
        assert "\xa0" not in value
        assert "  " not in value
        assert value == value.strip()


def test_dates_become_iso_strings(parsed):
    assert parsed["dinivig"].iloc[0] == "2026-01-01"


def test_blank_rows_are_dropped(parsed):
    # The fixture carries a trailing blank spacer row, as the real files do.
    assert parsed["cclasstrib"].notna().all()


def test_a_workbook_without_the_right_headers_is_rejected():
    import io

    import openpyxl

    workbook = openpyxl.Workbook()
    workbook.active.append(["something", "else"])
    buffer = io.BytesIO()
    workbook.save(buffer)
    with pytest.raises(FeedError):
        cclasstrib.parse(buffer.getvalue())


def test_list_versions_reads_dated_entries_and_ignores_other_tables():
    entries = cclasstrib.list_versions(listing_html=LISTING_FRAGMENT)

    assert [entry["date"] for entry in entries] == ["2025-12-15", "2026-06-23"]
    assert entries[0]["published"] == "15/12/2025"
    assert entries[0]["url"] == cclasstrib.DOCUMENT_URL
    assert entries[-1]["url"].endswith("exibirArquivo.aspx?conteudo=D5b4Ov84WDg=")
    assert all("Biocombust" not in entry["title"] for entry in entries)


def test_current_document_is_the_newest_release():
    current = cclasstrib.current_document(listing_html=LISTING_FRAGMENT)
    assert current["date"] == "2026-06-23"
    assert current["url"].endswith("conteudo=D5b4Ov84WDg=")


def test_current_document_refuses_an_empty_listing():
    with pytest.raises(FeedError):
        cclasstrib.current_document(listing_html="<html><body>nothing here</body></html>")


def test_registry_points_at_this_module():
    feeds = load_feeds(Path(__file__).parents[1] / "feeds.yaml")
    feed = feeds["cclasstrib"]
    assert feed.enabled is True
    assert feed.parser == "govdiff.feeds.cclasstrib"
    assert feed.key_fields == ["cclasstrib"]
    assert feed.load_parser() is cclasstrib
    assert feeds["sat69b"].enabled is False
