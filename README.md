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
| `sat69b` | Mexico, SAT - Listado completo 69-B | registered, no parser yet |

`sat69b` is still a stub in `feeds.yaml` with its probed URL.

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
```

`data/<feed>/<version>/` holds `data.parquet` plus a `meta.json` sidecar (schema, source URL, fetch time,
`Last-Modified`, sha256, row count). `diffs/<feed>/<from>__<to>.jsonl` holds one JSON object per changed
record, with a `.summary.json` beside it. `raw/` keeps source files up to 2 MB for provenance; the 46 MB SAT workbook is parsed in
memory and discarded, so only its sha256, size and `Last-Modified` survive in the sidecar.

## Ground rules

Plain unauthenticated GETs with a browser User-Agent, 40 s timeout, one retry. A 403/429/503 or a
challenge page raises `SourceChallenged` and the run stops - no proxy, no renderer, no bypass. Snapshots
are written only when the content hash or `Last-Modified` changes.

Code is MIT. The archived data is public government data, reproduced with attribution - see `LICENSE`.
