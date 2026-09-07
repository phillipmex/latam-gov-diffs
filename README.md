# latam-gov-diffs

A nightly archive and **machine-readable change feed** for Latin American government reference data.

Governments publish these tables as spreadsheets and quietly restructure them. This repository fetches
each source, stores a dated snapshot as Parquet, and commits a record-level diff against the previous
version. The diff, not the file, is the product.

## Feeds

| id | source | status |
|---|---|---|
| `cclasstrib` | Brazil, Portal Nacional da NF-e - IBS/CBS tax classification table | **live** |
| `catcfdi` | Mexico, SAT - CFDI 4.0 catalogues (Anexo 20) | **live** |
| `sat69b` | Mexico, SAT - Listado completo 69-B | **live** |

### What `catcfdi` covers

One SAT workbook, 25 catalogues, 362,345 rows. Every sheet of Anexo 20 is parsed, with the two
that SAT splits over several sheets (`c_CodigoPostal`, `c_Colonia`) put back together:

`c_Aduana`, `c_ClaveProdServ`, `c_ClaveUnidad`, `c_CodigoPostal`, `c_Colonia`, `c_Estado`,
`c_Exportacion`, `c_FormaPago`, `c_Impuesto`, `c_Localidad`, `c_Meses`, `c_MetodoPago`,
`c_Moneda`, `c_Municipio`, `c_NumPedimentoAduana`, `c_ObjetoImp`, `c_Pais`, `c_PatenteAduanal`,
`c_Periodicidad`, `c_RegimenFiscal`, `c_TasaOCuota`, `c_TipoDeComprobante`, `c_TipoFactor`,
`c_TipoRelacion`, `c_UsoCFDI`.

All 25 live in one Parquet per version with a leading `catalogo` column, and rows are keyed by
`(catalogo, clave, clave_2, clave_3)`. The catalogue name is part of the key on purpose: `01` is
a valid code in `c_Exportacion`, `c_Periodicidad`, `c_Meses` and `c_ObjetoImp`, and those four
rows must never be compared with each other. The extra key parts carry the second and third
columns that some catalogues need - a colonia number only identifies a neighbourhood together
with its postal code, and a customs patent only together with its office and year.

CFDI 3.3 is out of scope: its catalogue was last republished in March 2023 and 3.3 invoices
stopped being issuable in 2022.

### What `sat69b` covers

The SAT list of taxpayers presumed to have invoiced operations that never happened - Article 69-B
of the Codigo Fiscal de la Federacion, the "empresas factureras" blacklist. 14,234 rows, one per
proceeding, each carrying the taxpayer's RFC, name, current stage, and the office numbers and
publication dates for every stage it has passed through. The four stages are `Presunto` (SAT has
published a presumption), `Desvirtuado` (the taxpayer rebutted it), `Definitivo` (the presumption
stands, and invoices issued by that RFC lose their tax effect) and `Sentencia Favorable` (a court
overturned it). Landing on the definitive list is a commercial event for everyone who bought from
that RFC, which is why the date a name appears is worth more than the list itself.

Rows are keyed by RFC plus the presumption office number, not by RFC alone: 261 rows share an RFC
with another row, because the same taxpayer can be presumed twice in unrelated proceedings, and
66 of those pairs are even in the same stage. The stage is deliberately **not** part of the key,
so a taxpayer moving from `Presunto` to `Definitivo` shows up as one changed record rather than a
removal plus an addition. 91 rows have their RFC suppressed to `XXXXXXXXXXXX` by court order and
cannot be told apart by any column; the differ falls back to positional occurrence numbers for
those, which is honest but not stable between versions.

Publication dates are kept exactly as SAT wrote them, with an ISO sibling column added only where
the value is unambiguously one `dd/mm/yyyy` date. Cells holding two dates, or an unformatted Excel
serial that SAT never converted back, keep the source string and get no ISO value rather than a
guess.

**This feed has no history before this repository.** SAT publishes the current list only - there
is no archive, no dated filenames, and nothing to bootstrap. History for `sat69b` starts
**2026-09-07**, the day it was first snapshotted here, and every day not archived is lost for good.

## Honest note on the moat

The NF-e portal keeps every dated cClassTrib release on its listing page, so that raw history is
reproducible by anyone. SAT is thinner than it looked: the Anexo 20 page links only the current
CFDI 4.0 workbook, and the older dated files stay reachable at their own URLs without being linked
anywhere, so back-versions can be re-downloaded only if you already wrote the URL down. Either way,
what is not published anywhere is the **per-revision diff**: which codes were added, which fields
changed, and when. That change history - and the change feed built on it - is what this project
makes. The SAT 69-B list is the one genuinely unbackfillable feed: the publisher keeps the current
snapshot only, so every day not archived is lost.

## Running it

```
pip install -r requirements.txt && pip install -e .
govdiff status                   # feeds, version count, last fetch, last result
govdiff run cclasstrib           # fetch, snapshot if changed, diff vs previous
govdiff run                      # every enabled feed
govdiff bootstrap cclasstrib     # load the publisher's whole back catalogue
govdiff bootstrap catcfdi        # same, for any feed whose parser lists versions
govdiff rediff cclasstrib        # rebuild every diff from the stored snapshots, no network
```

`data/<feed>/<version>/` holds `data.parquet` plus a `meta.json` sidecar (schema, source URL, fetch time,
`Last-Modified`, sha256, row count). `diffs/<feed>/<from>__<to>.jsonl` holds one JSON object per changed
record, with a `.summary.json` beside it. `raw/` keeps source files up to 2 MB for provenance; the 46 MB SAT workbook
and the 4.4 MB 69-B list are parsed in memory and discarded, so only their sha256, size and `Last-Modified`
survive in the sidecar.

## The diff format

Each line of a `.jsonl` diff carries **only what changed**, never a whole row for context. The
alternative is expensive: one catCFDI revision touching 8,026 records wrote 20.6 MB, because a
catalogue row is 86 columns of which about 80 are empty for any given catalogue, and every one of
those nulls was written out twice. The same revision is 2.7 MB in this format.

An addition carries the new row with its empty columns dropped:

```json
{"op": "added", "key": {"catalogo": "c_PatenteAduanal", "clave": "1889", "clave_2": "", "clave_3": ""}, "after": {"catalogo": "c_PatenteAduanal", "clave": "1889", "c_patenteaduanal": "1889", "inicio_de_vigencia_de_la_patente": "2024-09-03"}}
```

A removal is the same shape with `before`:

```json
{"op": "removed", "key": {"cclasstrib": "1"}, "before": {"cclasstrib": "1", "cst_ibs_cbs": "000", "descricao_cclasstrib": "Situacoes tributadas integralmente pelo IBS e CBS.", "descricao_cst_ibs_cbs": "Tributacao integral"}}
```

A change lists **only the columns that moved**, each with both values:

```json
{"op": "changed", "key": {"cclasstrib": "000001"}, "fields": {"dataatualizacao": {"before": "2025-05-19", "after": "2025-11-19"}, "indnfgas": {"before": "0", "after": "1"}}}
```

`key` is the feed's `key_fields` from `feeds.yaml`. When a source ships two rows with the same key,
they are matched by position and the key gains an `_occurrence` number so they are not silently
merged. The `.summary.json` beside each diff declares `"format": 2` and, for changes, a
`changed_fields` count of how many records each column moved on - the fastest way to see that a
revision was a mass re-dating rather than real movement.

## Ground rules

Plain unauthenticated GETs with a browser User-Agent, 40 s timeout, one retry. A 403/429/503 or a
challenge page raises `SourceChallenged` and the run stops - no proxy, no renderer, no bypass. Snapshots
are written only when the content hash or `Last-Modified` changes.

Code is MIT. The archived data is public government data, reproduced with attribution - see `LICENSE`.
