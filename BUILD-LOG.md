# Build log

## 2026-09-07 - day 1

Built the shared core (fetch, snapshot, diff, CLI, feed registry), the first feed adapter, and ran the
cClassTrib back-catalogue bootstrap.

### What was built

- `govdiff.fetch` - one plain unauthenticated GET per URL, browser User-Agent, 40 s timeout, one retry
  after 30 s and only for a transport fault. 403/429/503 or a challenge marker in a textual body raises
  `SourceChallenged`; there is no bypass path in the code. Conditional requests use the stored
  `ETag`/`Last-Modified` from `.state/<feed>.json`, which is committed.
- `govdiff.snapshot` - version id `<date>-<sha256[:8]>`, Parquet plus a `meta.json` sidecar
  (schema, source URL, fetched_at, last_modified, sha256, row_count). Idempotent: a content hash that
  is already stored never produces a second version. Raw files at or below 2 MB are kept under
  `raw/<feed>/<date>/`; larger ones are parsed in memory and discarded.
- `govdiff.diff` - generic differ over two versions keyed by `key_fields`. Writes
  `diffs/<feed>/<from>__<to>.jsonl` (one object per changed record) and a `.summary.json` with counts
  plus the schema drift (`fields_added`, `fields_removed`).
- `govdiff.feeds.cclasstrib` - workbook parser and `list_versions()` back-catalogue reader.
- CLI `govdiff run|bootstrap|status`, and a nightly GitHub Actions workflow at 06:15 UTC.

### Bootstrap results (real numbers)

The listing page indexes **10** dated cClassTrib releases, back to 2024-12-07. All 10 fetched, parsed
and snapshotted; 9 consecutive diffs written.

| published | version id | rows | bytes |
|---|---|---:|---:|
| 07/12/2024 | 2024-12-07-67a71e9a | 94 | 29,405 |
| 06/05/2025 | 2025-05-06-eb953b54 | 125 | 44,022 |
| 19/05/2025 | 2025-05-19-12c38b66 | 125 | 46,016 |
| 18/06/2025 | 2025-06-18-f18c6aec | 132 | 59,380 |
| 03/10/2025 | 2025-10-03-b5ed31f4 | 142 | 79,462 |
| 24/11/2025 | 2025-11-24-431d4217 | 145 | 122,346 |
| 15/12/2025 | 2025-12-15-15ce63cb | 145 | 120,939 |
| 28/01/2026 | 2026-01-28-0825eadf | 154 | 115,113 |
| 15/04/2026 | 2026-04-15-cc0242ed | 156 | 117,399 |
| 23/06/2026 | 2026-06-23-1448cb63 | 164 | 156,899 |

| diff | added | changed | removed | unchanged | columns +/- |
|---|---:|---:|---:|---:|---|
| 2024-12-07 -> 2025-05-06 | 43 | 82 | 12 | 0 | +20 / -2 |
| 2025-05-06 -> 2025-05-19 | 0 | 125 | 0 | 0 | +1 / -18 |
| 2025-05-19 -> 2025-06-18 | 7 | 125 | 0 | 0 | +13 / -1 |
| 2025-06-18 -> 2025-10-03 | 12 | 130 | 2 | 0 | +23 / -5 |
| 2025-10-03 -> 2025-11-24 | 7 | 25 | 4 | 113 | 0 / -1 |
| 2025-11-24 -> 2025-12-15 | 0 | 132 | 0 | 13 | 0 / -1 |
| 2025-12-15 -> 2026-01-28 | 9 | 37 | 0 | 108 | 0 / 0 |
| 2026-01-28 -> 2026-04-15 | 2 | 25 | 0 | 129 | 0 / 0 |
| 2026-04-15 -> 2026-06-23 | 8 | 156 | 0 | 0 | +6 / 0 |

On disk: `raw/` 890,981 B (10 files, largest 156,899 B), `data/` 639,098 B, `diffs/` 913,356 B.

### Surprises in the data

1. **No `ETag`, no `Last-Modified` on documents.** The NF-e portal sends neither for
   `exibirArquivo.aspx`, so the content hash is the only change signal and the version date has to come
   from the listing's own publication date. Conditional-request support is still in the fetcher for the
   SAT feeds, which do send `Last-Modified`.
2. **Each release has its own permanent URL.** `document_url` in `feeds.yaml` is a fixed release, not a
   moving "current" pointer, so a run that only fetched that URL would archive the same file forever.
   `run` therefore reads the listing once per run and takes the newest release. The URL the gate handed
   over as current (15/12/2025) is in fact the seventh of ten - the portal has published three releases
   since.
3. **10 releases, not the 8 counted at day 0.** Four of them do not mention "cClassTrib" anywhere in
   their listing description, so selecting on the title ("Classificacao Tributaria do IBS") is required.
4. **Mixed code formats in the first release.** 2024-12-07 has 8 unpadded codes (`1`..`8`) alongside 86
   six-digit ones; from 2025-05-06 everything is six digits. That accounts for most of the 12 "removed"
   records in the first diff - only `400002`, `810002` and `900001` are genuine removals. The codes are
   kept exactly as published; no padding was invented.
5. **The publisher ships a duplicate key.** Code `200003` appears twice in 2024-12-07 (Art. 139 §3 and
   Art. 140 I). The differ keeps duplicates apart with an occurrence suffix rather than dropping or
   merging them, and reports the count in the summary.
6. **Heavy schema churn.** Raw column count went 8 -> 32 -> 9 -> 21 -> 39 -> 38 -> 37 -> 42 -> 38 -> 82,
   the sheet name changed with almost every release, the workbook went from one sheet to two, and the
   2025-05-06 release repeats six header labels. The parser identifies the sheet by header content and
   de-duplicates header names. A dropped column makes every row read as "changed" (2025-05-06 ->
   2025-05-19 dropped 18 columns; all 125 rows changed) - that is correct, and `fields_removed` in the
   summary explains it.
7. **A naive challenge check fails on this publisher.** The portal's own navigation links to
   `consultaRecaptcha.aspx`, so a bare "captcha"/"recaptcha" substring match reads the ordinary listing
   page as an anti-bot wall. Detection now matches widget and script markers, not bare words. This bit
   on the first bootstrap attempt.

### Requests made

11 to `nfe.fazenda.gov.br` during the bootstrap (1 listing + 10 documents, 3 s apart), plus 2 for the
`run` verification. Nothing else was fetched.

### Tests

`pytest -q`: 40 passed. Coverage: differ (added/removed/changed, new column, duplicate keys, empty-cell
equivalence, file output), snapshot idempotence and version-id rules, raw size guard, challenge
detection (403/429/503, proof-of-work body, Cloudflare interstitial, reCAPTCHA widget, the
false-positive listing page, binary bodies), conditional-request headers and 304 handling, filename
sanitisation, and the cClassTrib parser against a 20-row fixture cut from the real 2025-12-12 file.

### Day 2

1. **`catcfdi` adapter.** The Anexo 20 workbook is ~46.5 MB of legacy `.xls` with many sheets: fetch it
   into memory, parse with `xlrd`, never write the raw file (it is 23x the 2 MB raw ceiling). It needs
   one snapshot per catalogue sheet, not one per workbook, so `snapshot.write_snapshot` will need a
   multi-table form and `feeds.yaml` an entry shape that carries per-sheet key fields.
2. **Back-versions from "Versiones anteriores"** on the Anexo 20 landing page. Fetch the document URLs
   only - the omawww landing pages are SharePoint stubs behind an F5 fingerprinting script and are never
   to be scraped. Extract the dated `catCFDI_V_*_YYYYMMDD.xls` URLs and bootstrap them the same way.
3. **Watch the challenge rule.** If any SAT document URL starts returning a challenge, that feed stops
   that day and the nightly job fails loudly. That is the designed behaviour, not a bug to work around.

## 2026-09-07 - day 2

### Version discovery (one request, made before anything else)

`GET http://omawww.sat.gob.mx/tramitesyservicios/Paginas/anexo_20.htm` -> 200, 23,228 B,
`Last-Modified: Thu, 03 Sep 2026 15:03:01 GMT`. That is the only HTML page fetched in this
build. Every `catCFDI` link on it:

| filename | version | date in filename | linked as | in scope |
|---|---|---|---|---|
| `documentos/catCFDI_V_4_20260903.xls` | CFDI 4.0 | 2026-09-03 | "Catalogos CFDI version 4.0", dated 03/09/2026 | yes |
| `documentos/catCFDI_V_33_31032023.xls` | CFDI 3.3 | 2023-03-31 | "Catalogos CFDI Version 3.3 (xls)", dated 31/03/2023 | no - 3.3 is out of scope |

**There is no back catalogue of catCFDI files on this page.** The page says "Versiones
anteriores" twice, and both times it is about the *guias de llenado* and the *preguntas
frecuentes*, not the catalogues; both link to `historico_guia_anexo20.htm`, a second HTML
landing page this build is not allowed to fetch. The day-0 probe recorded
`catCFDI_V_4_20241204.xls` as a dated filename it had seen, so that one known URL is tried
directly as a document request (below); no other back-version URL is guessed.

### What was built

- `govdiff.feeds.catcfdi` - the Anexo 20 workbook parser, plus `list_versions()` and
  `current_document()`, which read the Anexo 20 page once per run.
- `runner.bootstrap_feed(feed_id)` - the day-1 back-catalogue walk, generalised to any feed whose
  parser exposes `list_versions()`. `bootstrap_cclasstrib` stays as a one-line wrapper with its
  behaviour unchanged, and `govdiff bootstrap <feed>` now accepts any such feed. A release that
  404s is recorded and the walk continues instead of aborting.
- `feeds.yaml`: `catcfdi` enabled, parser `govdiff.feeds.catcfdi`, key fields
  `[catalogo, clave, clave_2, clave_3]`.

### Storage shape: one Parquet per version, not one per sheet

The snapshot layer writes exactly one `data.parquet` per version and the differ reads exactly one
frame per side. A single long frame - `catalogo` first, then up to three key columns, then the
union of every sheet's own columns - therefore needed **no change at all** to `snapshot.py`,
`diff.py` or `_ingest`. One Parquet per sheet would have needed a new directory convention under
the version directory, a sidecar that describes several tables, a differ that loops over them and
a CLI that reports per table. Day 1 predicted the multi-table form would be necessary; it is not.

The long frame is 86 columns wide and mostly null, which Parquet's dictionary encoding absorbs:
5.5 MB per version, well under the 10 MB the brief asked to be flagged.

The diff key is `(catalogo, clave, clave_2, clave_3)`. The catalogue name has to be in the key:
`01` is a live code in `c_Exportacion`, `c_Periodicidad`, `c_Meses` and `c_ObjetoImp` at the same
time. `clave_2` and `clave_3` are empty for the 20 catalogues keyed on a single column.

### Sheet inventory (2026-09-03 workbook)

| # | sheet | catalogue | header row | 2nd header line | key columns | cols | rows in sheet |
|--:|---|---|--:|---|---|--:|--:|
| 1 | `c_FormaPago` | `c_FormaPago` | 5 | - | `c_formapago` | 14 | 22 |
| 2 | `c_Moneda` | `c_Moneda` | 4 | - | `c_moneda` | 6 | 183 |
| 3 | `c_TipoDeComprobante` | `c_TipoDeComprobante` | 4 | - | `c_tipodecomprobante` | 5 | 5 |
| 4 | `c_Exportacion` | `c_Exportacion` | 4 | - | `c_exportacion` | 4 | 4 |
| 5 | `c_MetodoPago` | `c_MetodoPago` | 5 | - | `c_metodopago` | 4 | 2 |
| 6 | `c_CodigoPostal_Parte_1` | `c_CodigoPostal` | 5 | yes | `c_codigopostal` | 16 | 60,082 |
| 7 | `c_CodigoPostal_Parte_2` | `c_CodigoPostal` | 5 | yes | `c_codigopostal` | 16 | 35,667 |
| 8 | `c_Periodicidad` | `c_Periodicidad` | 4 | - | `c_periodicidad` | 4 | 5 |
| 9 | `c_Meses` | `c_Meses` | 4 | - | `c_meses` | 4 | 18 |
| 10 | `c_TipoRelacion` | `c_TipoRelacion` | 4 | - | `c_tiporelacion` | 4 | 7 |
| 11 | `c_RegimenFiscal` | `c_RegimenFiscal` | 5 | - | `c_regimenfiscal` | 6 | 19 |
| 12 | `c_Pais` | `c_Pais` | 4 | - | `c_pais` | 6 | 250 |
| 13 | `c_UsoCFDI` | `c_UsoCFDI` | 4 | yes | `c_usocfdi` | 7 | 24 |
| 14 | `c_ClaveProdServ` | `c_ClaveProdServ` | 4 | - | `c_claveprodserv` | 9 | 52,513 |
| 15 | `c_ClaveUnidad` | `c_ClaveUnidad` | 5 | - | `c_claveunidad` | 7 | 2,417 |
| 16 | `c_ObjetoImp` | `c_ObjetoImp` | 4 | - | `c_objetoimp` | 4 | 8 |
| 17 | `c_Impuesto` | `c_Impuesto` | 4 | - | `c_impuesto` | 7 | 3 |
| 18 | `c_TipoFactor` | `c_TipoFactor` | 4 | - | `c_tipofactor` | 3 | 3 |
| 19 | `c_TasaOCuota` | `c_TasaOCuota` | 4 | yes | `rango_o_fijo`, `impuesto`, `valor_maximo` | 9 | 19 |
| 20 | `c_Aduana` | `c_Aduana` | 4 | - | `c_aduana` | 4 | 50 |
| 21 | `c_NumPedimentoAduana` | `c_NumPedimentoAduana` | 4 | - | `c_aduana`, `patente`, `ejercicio` | 6 | 59,027 |
| 22 | `c_PatenteAduanal` | `c_PatenteAduanal` | 4 | - | `c_patenteaduanal` | 3 | 3,414 |
| 23 | `C_Colonia_1` | `c_Colonia` | 4 | - | `c_colonia`, `c_codigopostal` | 3 | 60,100 |
| 24 | `C_Colonia_2` | `c_Colonia` | 4 | - | `c_colonia`, `c_codigopostal` | 3 | 60,100 |
| 25 | `C_Colonia_3` | `c_Colonia` | 4 | - | `c_colonia`, `c_codigopostal` | 3 | 25,166 |
| 26 | `c_Estado` | `c_Estado` | 4 | - | `c_estado` | 5 | 95 |
| 27 | `C_Localidad` | `c_Localidad` | 4 | - | `c_localidad`, `c_estado` | 5 | 664 |
| 28 | `C_Municipio` | `c_Municipio` | 4 | - | `c_municipio`, `c_estado` | 5 | 2,478 |
| | **28 sheets** | **25 catalogues** | | | | | **362,345** |

Header rows are 0-indexed. Rows are counted after the title/metadata block, the blank spacers and
the fully-empty rows are dropped. Catalogue totals, both versions:

| catalogue | rows 2024-12-04 | rows 2026-09-03 | delta |
|---|--:|--:|--:|
| `c_Aduana` | 50 | 50 | - |
| `c_ClaveProdServ` | 52,513 | 52,513 | - |
| `c_ClaveUnidad` | 2,417 | 2,417 | - |
| `c_CodigoPostal` | 95,749 | 95,749 | - |
| `c_Colonia` | 145,366 | 145,366 | - |
| `c_Estado` | 95 | 95 | - |
| `c_Exportacion` | 4 | 4 | - |
| `c_FormaPago` | 22 | 22 | - |
| `c_Impuesto` | 3 | 3 | - |
| `c_Localidad` | 664 | 664 | - |
| `c_Meses` | 18 | 18 | - |
| `c_MetodoPago` | 2 | 2 | - |
| `c_Moneda` | 183 | 183 | - |
| `c_Municipio` | 2,463 | 2,478 | +15 |
| `c_NumPedimentoAduana` | 51,208 | 59,027 | +7,819 |
| `c_ObjetoImp` | 5 | 8 | +3 |
| `c_Pais` | 250 | 250 | - |
| `c_PatenteAduanal` | 3,335 | 3,414 | +79 |
| `c_Periodicidad` | 5 | 5 | - |
| `c_RegimenFiscal` | 19 | 19 | - |
| `c_TasaOCuota` | 19 | 19 | - |
| `c_TipoDeComprobante` | 5 | 5 | - |
| `c_TipoFactor` | 3 | 3 | - |
| `c_TipoRelacion` | 7 | 7 | - |
| `c_UsoCFDI` | 24 | 24 | - |
| **total** | **354,429** | **362,345** | **+7,916** |

### Bootstrap results (real numbers)

Two versions exist and both were fetched, oldest first, 3 s apart. No 404s.

| published | version id | sha256[:8] | rows | source bytes | fetch |
|---|---|---|---:|---:|---:|
| 04/12/2024 | `2024-12-04-a4b88178` | `a4b88178` | 354,429 | 47,913,472 | 43.8 s |
| 03/09/2026 | `2026-09-03-a5ce7a60` | `a5ce7a60` | 362,345 | 48,812,544 | 46.0 s |

Both are 86 columns; `fields_added` and `fields_removed` are both empty, so no catalogue gained or
lost a column in 21 months. One diff, `2024-12-04-a4b88178 -> 2026-09-03-a5ce7a60`:

| catalogue | added | changed | removed |
|---|---:|---:|---:|
| `c_ClaveProdServ` | 0 | 15 | 0 |
| `c_CodigoPostal` | 0 | 93 | 0 |
| `c_Municipio` | 15 | 0 | 0 |
| `c_NumPedimentoAduana` | 7,819 | 0 | 0 |
| `c_ObjetoImp` | 3 | 0 | 0 |
| `c_PatenteAduanal` | 79 | 0 | 0 |
| `c_TasaOCuota` | 1 | 0 | 1 |
| **total** | **7,917** | **108** | **1** |

354,320 rows unchanged, 0 duplicate keys on either side. Twenty-one months apart, and the only
catalogues that moved are customs (new pedimento numbers and broker patents), 15 new
municipalities, 3 new `c_ObjetoImp` codes, one IEPS quota, 15 product-code descriptions and 93
postal codes. That is the product: a 46 MB workbook reduced to 8,026 lines a reader can check.

### Surprises

1. **There is no "Versiones anteriores" list for the catalogues.** The Anexo 20 page uses that
   phrase twice and both times means the *guias de llenado* and the *preguntas frecuentes*. It
   links exactly two catalogue workbooks: the current 4.0 one and the retired 3.3 one. Day 0 read
   the phrase as covering the catalogues; it does not. Day 1's plan to "extract the dated URLs
   from Versiones anteriores" had nothing to extract.
2. **Unlinked back-versions are still live.** `catCFDI_V_4_20241204.xls`, recorded by the day-0
   probe and linked from nowhere on the page today, still returns 200 with its original
   `Last-Modified` of 04/12/2024. SAT does keep old files; it just stops pointing at them, so a
   URL nobody wrote down is effectively gone. That single URL is listed in the adapter as a known
   back-version and is the only reason a day-2 diff exists at all.
3. **Header rows sit at four different depths, and four sheets have two of them.** The header is
   on row 4 or row 5 depending on how many blank spacers SAT left under the title and the
   `Version CFDI` / `Version catalogo` metadata pair. `c_UsoCFDI` writes `Fisica`/`Moral` on a
   second line, `c_TasaOCuota` writes `Valor minimo`/`Valor maximo`, and both `c_CodigoPostal`
   sheets write eight time-zone sub-columns. The parser finds the header as the first row that
   names a `c_`-prefixed column and labels at least two cells, then folds in a following line
   whose first cell is empty but whose others are filled.
4. **28 sheets, 25 catalogues.** SAT splits `c_CodigoPostal` over two sheets and `c_Colonia` over
   three, purely because of the old `.xls` 65,536-row limit. They are re-joined before diffing, so
   a postal code moving from part 1 to part 2 between releases is not a deletion plus an insertion.
5. **Five catalogues are not keyed by their first column.** Colonia numbers restart inside every
   postal code (`0001` appears 1,803 times), locality and municipality numbers restart inside
   every state, and a pedimento needs customs office plus broker patent plus year. With the
   composite keys in place there are zero duplicate keys in either version.
6. **`c_TasaOCuota` is not a code table.** Its rows are tax rates, and the `c_TasaOCuota` column
   holds only the lower bound of a range - empty on the 16 fixed-rate rows. It is keyed on
   `(rango_o_fijo, impuesto, valor_maximo)`, which has the honest cost that the IEPS quota moving
   from 66.5062 to 72.1605 reads as one removal plus one addition rather than one change. That is
   the single `+1/-1` in the diff. There is no stable identifier in the sheet to key on instead.
7. **`c_TipoDeComprobante` ships a code-less row** carrying only the `Valor maximo` limits. Rows
   whose key parts are all empty are dropped; it is the only such row in the workbook.
8. **The diff file is 20.6 MB for 8,026 records.** Added and removed records carry the whole row,
   and a row here is 86 columns of which about 80 are null for any given catalogue. The day-1
   differ is left untouched - stripping nulls would change the cClassTrib output too - but a
   null-stripping option is the obvious later cleanup if this keeps growing.
9. **SAT sends both `ETag` and `Last-Modified`** for the document, unlike the NF-e portal. After
   the first `govdiff run` the state file carries both, so the nightly job is a conditional request
   from now on and should get a 304 instead of 46 MB.

### Sizes on disk

| path | bytes |
|---|---:|
| `data/catcfdi/2024-12-04-a4b88178/data.parquet` | 5,509,052 |
| `data/catcfdi/2026-09-03-a5ce7a60/data.parquet` | 5,522,918 |
| `data/catcfdi/` (both versions, with sidecars) | 11,045,610 |
| `diffs/catcfdi/` (one `.jsonl` plus its summary) | 20,628,510 |
| `data/` total | 11,684,708 |
| `diffs/` total | 21,541,866 |
| `raw/` | 890,981 - unchanged, nothing raw was kept for `catcfdi` |

The two source workbooks, 47.9 MB and 48.8 MB, were streamed to a temp directory outside the
repository, parsed, and deleted; their sha256, byte size and `Last-Modified` live in the sidecars.
Parsing one workbook takes about 8 seconds.

### Requests made

Eight, all to `omawww.sat.gob.mx`, none retried, no 403/429/503 and no challenge marker anywhere:

| run | requests |
|---|---|
| discovery | `anexo_20.htm`, then the two 4.0 documents (44.8 s, 45.0 s) |
| `govdiff bootstrap catcfdi` | `anexo_20.htm`, then the two 4.0 documents, 3 s apart |
| `govdiff run catcfdi` | `anexo_20.htm`, then the current document |

Three HTML fetches across three separate runs - one per run, always the same single page, never
`historico_guia_anexo20.htm` or any other landing page. The 3.3 workbook was listed and never
fetched. Each document fetch took 44-46 s for ~47 MB, which is inside the 40 s timeout because
that timeout is per socket read, not per transfer.

### Tests

`pytest -q`: **65 passed in 0.92s** (40 from day 1, 25 new). The new tests cover the parser against
a three-sheet fixture cut from the real 2026-09-03 workbook (`c_Exportacion`, `c_Periodicidad`,
`c_UsoCFDI`, 20 rows each, saved as `.xlsx`); header-row detection at four depths including the
failure case; two-line header merging; catalogue-name collapsing for split sheets; key selection
for single and composite keys; the loud failure when a key column disappears; listing parsing for
both CFDI versions; and three composite-key diff cases - the same code in two catalogues diffs as
one change and not as an add plus a remove, and two colonias sharing code `0001` under different
postal codes stay apart.

One day-1 assertion changed: `test_registry_points_at_this_module` asserted that `catcfdi` was
disabled in `feeds.yaml`. It is enabled now, so that line is gone; the `sat69b` half is untouched.

The parser picks its Excel engine from the container's magic bytes - `xlrd` for the `.xls` SAT
actually ships, `openpyxl` for the `.xlsx` fixture, because xlrd 2.x refuses `.xlsx` outright.

### Day 3: sat69b

1. **Archive first, diff second.** This is the one feed with no public back-series: SAT keeps only
   the current `Listado_Completo_69-B.csv` and organises it by legal category, not by date. Get it
   snapshotting nightly before anything else - every day not archived is lost for good. There is no
   listing page, so no `list_versions()` and no bootstrap; `run` is the whole feed.
2. **`Last-Modified` is the only version signal.** The day-0 probe saw
   `Last-Modified: Thu, 22 Jan 2026 22:59:33 GMT` on a 4.4 MB file - twice the 2 MB raw ceiling, so
   decide deliberately whether to raise `RAW_KEEP_MAX_BYTES` for provenance on this feed or let the
   Parquet be the only copy.
3. **Key on RFC, not on RFC plus status.** A taxpayer moves between the four legal situations
   (presunto -> definitivo -> desvirtuado -> sentencia favorable) and that movement is the entire
   story, so the situation must stay out of the key and read as a change, not as a remove plus an
   add. Expect duplicate RFCs and check before choosing.
4. **Expect the fetch to fail sometimes.** Timing was inconsistent at day 0 - one check from this
   network timed out where the probe took 0.14 s. Let it fail loudly rather than retrying around it.

## 2026-09-07 - day 3

Slimmed the diff format and migrated the whole archive to it, then built `sat69b` - the SAT 69-B
list, the one feed in this repository that nobody can backfill.

### Part A: the diff format is now format 2

The day-2 catCFDI diff was **20.6 MB for 8,026 changed records**. The cause was the format, not the
data: a catCFDI row is 86 columns wide and roughly 80 of them are null for any given catalogue, and
format 1 wrote a whole row on `added`/`removed` (nulls included) and two parallel `before`/`after`
objects on `changed`. A nightly 20 MB commit would have made the public repository unusable inside
a month.

Format 2 writes only what moved:

- `added` -> `{"op", "key", "after"}`, and `after` drops every null column.
- `removed` -> `{"op", "key", "before"}`, same rule. There is no `"after": null` key any more.
- `changed` -> `{"op", "key", "fields"}`, where `fields` holds one entry per column that differs,
  each `{"before": ..., "after": ...}`. Columns that did not move are absent.

`.summary.json` keeps its shape and gains two things: `"format": 2`, and `changed_fields`, a count
of how many records each column moved on. That second field turns out to be the most useful line in
the file - it is what distinguishes a revision that re-dated 132 rows from one that changed real
content.

`govdiff rediff <feed>` rebuilds every consecutive diff of a feed from the stored Parquet snapshots,
with no network access at all. The snapshots are the record; a diff is derived. Each pair is written
back over the same `<from>__<to>` filename, so the format-1 files were replaced rather than left
beside their successors - `git status` showed 10 modified `.jsonl` files and 10 modified summaries,
and no additions or deletions under `diffs/`.

**Counts are unchanged, and this was checked rather than assumed.** All 10 summaries were saved
before the migration and compared afterwards on `added`, `removed`, `changed`, `unchanged`,
`rows_from`, `rows_to`, `fields_added`, `fields_removed`, `duplicate_keys_from` and
`duplicate_keys_to`: **10 summaries compared, 0 mismatches.** Every number in the day-1 and day-2
tables above still describes the files on disk.

Sizes:

| | format 1 | format 2 | change |
|---|--:|--:|---|
| `diffs/` total | 21,541,866 | 3,586,386 | **-83.4%** |
| `diffs/catcfdi/*.jsonl` | 20,627,995 | 2,671,236 | -87.1% |
| `diffs/cclasstrib/*.jsonl` | 907,091 | 904,022 | -0.3% |

The cClassTrib line is the honest part. Format 2 is not smaller everywhere: cClassTrib rows are
narrow and densely filled, so dropping nulls saves little, and the nested
`{"col": {"before": x, "after": y}}` is more verbose per moved column than format 1's two parallel
objects. Four of the nine cClassTrib diffs grew - the worst by 23,081 B (2025-06-18 -> 2025-10-03,
where 130 of 132 records changed) and 3,634 B (2026-04-15 -> 2026-06-23, all 156 records changed).
Five shrank, the best by 26,717 B. The format is chosen for the wide sparse case because that is
where the money is; on narrow dense tables it is a wash.

### Part B: sat69b

**One document, fetched twice, plus three HEADs.** `HEAD` then `GET` on
`http://omawww.sat.gob.mx/cifras_sat/Documents/Listado_Completo_69-B.csv`: 200, 4,566,277 B,
`Last-Modified: Thu, 22 Jan 2026 22:59:33 GMT`, `Content-Type: application/octet-stream`, saved to
a temp directory outside the repository. No HTML landing page was touched, and
`/cifras_sat/Documents/` was never requested.

**Encoding: cp1252, established, not guessed.** The file does not decode as UTF-8. It contains bytes
in the 0x80-0x9F range - typographic quotes SAT's own tooling emitted inside company names - which
are undefined control characters in latin-1 and printable in cp1252. So `detect_encoding` tries
utf-8-sig first, and only falls back to cp1252 when that range is actually used; a file that avoids
it is read as latin-1, where the two agree anyway.

**The header is line 2 (0-indexed), under two title rows.** The first 20 lines were inspected before
anything was parsed:

| line | content |
|--:|---|
| 0 | `"Informacion actualizada al 31 de diciembre de 2025; los listados a que se hace mencion, son de caracter publico..."` |
| 1 | `Listado completo de contribuyentes (Articulo 69-B del CFF),,,,,,,,,,,,,,,,,,,` |
| 2 | `No,RFC,Nombre del Contribuyente,Situacion del contribuyente,Numero y fecha de oficio global de presuncion SAT,...` (20 columns) |
| 3+ | data, starting `1,AAA080808HL8,"ASESORES EN AVALUOS Y ACTIVOS, S.A. DE C.V.",Sentencia Favorable,...` |

Both title rows are padded with the same 19 trailing commas as the data, so they cannot be told
from a header by field count. The detector uses content instead: the first line that parses to at
least three non-empty labels, one of which is `rfc`. Note that the "actualizada al" date in line 0
says **31 December 2025** while `Last-Modified` says 22 January 2026 - the content date and the
publication date are different things, and only the second one is a fact about the file.

**14,234 rows, 27 columns.** The source's 20 columns become 19 (the `No` ordinal is dropped) plus 8
ISO sibling columns. Dropping `No` is deliberate: it is a positional row number, so an insertion
anywhere near the top of an alphabetically-sorted file would renumber every row below it and turn a
one-record change into 14,000 changed records. It carries no information that the row does not.

Rows per "situacion del contribuyente":

| situacion | rows | what it means |
|---|--:|---|
| `Definitivo` | 11,270 | the presumption stands; invoices from that RFC have no tax effect |
| `Sentencia Favorable` | 1,638 | a court overturned it |
| `Presunto` | 986 | SAT has published a presumption, rebuttal window open |
| `Desvirtuado` | 340 | the taxpayer rebutted it successfully |
| **total** | **14,234** | |

**The key: RFC plus the presumption office number.** Decided by counting, not by guessing.

| candidate key | rows sharing a key |
|---|--:|
| `rfc` | 261 (170 of them real RFCs) |
| `rfc` + `situacion_del_contribuyente` | 66 among real RFCs |
| `rfc` + `numero_y_fecha_de_oficio_global_de_presuncion_sat` | **0** among real RFCs |

An RFC repeats because the same taxpayer can be presumed twice in two unrelated proceedings, years
apart - and 66 of those pairs are even in the same stage, so adding the stage does not rescue it.
The presumption office number identifies the proceeding, and every proceeding is unique per
taxpayer. The stage is deliberately kept **out** of the key: a taxpayer moving from `Presunto` to
`Definitivo` is the single most valuable event in this feed, and it must read as one changed record,
not as a removal plus an addition.

The remaining 74 duplicate-key rows are all `XXXXXXXXXXXX` - 91 rows whose RFC is suppressed by
court order. No combination of columns separates them, so they fall through to the differ's existing
occurrence-suffix mechanism (`_occurrence: 2`). That is positional and not stable between versions,
and it is recorded here as a known limitation rather than papered over.

**Dates keep the source string; ISO is an addition, never a replacement.** Each publication column
gets a `_iso` sibling immediately after it, filled only when the cell is one unambiguous
`dd/mm/yyyy` value. 185 cells across the file get no ISO value, out of 57,730 filled date cells:
179 hold two dates in one cell (`25/05/2022 - 26/04/2021`, a re-publication), 2 hold a raw Excel
serial (`44014`) SAT never formatted back to a date, and 4 are hand-typed variants of the two-date
form (`17/10/2019 27/08/2018`, `24/04/2023 -15/10/2020`, `01/12/2023- 24/02/2021`,
`01-12-2023- 23/05/2023`). All 185 keep their source text and get an empty ISO sibling. Nothing is
inferred.

**Change signal: `Last-Modified` plus the sha256 of the body.** The brief expected only
`Last-Modified`; the endpoint in fact also sends an ETag,
`"{E8180FE0-2E1C-4445-9381-A355CB4CFD85},24"`. That is a SharePoint document GUID with a version
counter, which tracks list-item revisions and not the bytes, so it is recorded in
`.state/sat69b.json` and in the sidecar but deliberately not used as a validator. `fetch()` gained
`use_etag`, and the parser sets `USE_ETAG = False`; the conditional request asks on
`If-Modified-Since` alone and the content hash settles the rest.

**One version, and no diff was invented.** `govdiff run sat69b` stored `2026-01-22-54b95d41`,
14,234 rows, `data/sat69b/` 765,584 B. There is no `diffs/sat69b/` directory and there will not be
one until SAT republishes. The second `govdiff run sat69b` returned `unchanged (304 Not Modified)` -
one conditional request, no body, no new version.

At 4.4 MB the file is over the 2 MB raw ceiling, so **no raw copy is committed**.
`RAW_KEEP_MAX_BYTES` was deliberately left at 2 MB rather than raised for this feed: the Parquet is
a faithful text-for-text copy of every cell, and the sidecar carries the sha256, byte size and
`Last-Modified` needed to prove it. Committing 4.4 MB of CSV nightly would repeat the exact mistake
Part A just fixed.

**The three sibling lists, HEAD only, once each.** These are the other Article 69 lists SAT
publishes, and the day-0 notes suggested they might sit beside the 69-B file:

| URL | status |
|---|--:|
| `/cifras_sat/Documents/Listado_Completo_69.csv` | 404 |
| `/cifras_sat/Documents/Listado_Completo_69_Cancelados.csv` | 404 |
| `/cifras_sat/Documents/Listado_Completo_69_No_localizados.csv` | 404 |

All three are gone from this directory, so **nothing was registered as a stub feed** and no body was
fetched. Whatever SAT does with the Article 69 lists today, it is not at these paths. The directory
listing itself was not probed - it returns 401 and the brief rules it out.

### Requests made

**Seven**, all to `omawww.sat.gob.mx`, none retried, no 403/429/503, no challenge marker:

| run | requests |
|---|---|
| probe | `HEAD` then `GET` on the 69-B CSV, 3 s apart |
| `govdiff run sat69b` | one `GET` |
| `govdiff run sat69b` (second) | one conditional `GET` -> 304 |
| sibling check | three `HEAD`s, 3 s apart |

Part A made none: `govdiff rediff` reads only the stored Parquet.

### Tests

`pytest -q`: **92 passed in 0.90s** (65 from day 2, 27 new or rewritten). The new work covers
encoding detection including the case that matters - a file using the 0x80-0x9F range must not be
read as latin-1 - header detection under padded title rows and its failure case, the dropped `No`
ordinal, ISO siblings for both ambiguous forms, all three key candidates, the registry wiring, and
an offline runner test that snapshots once and then answers 304 on the second run while proving the
conditional request carries `If-Modified-Since` and not `If-None-Match`.

`tests/fixtures/sat69b_sample.csv` is 11 rows cut byte-for-byte from the real file, with both title
rows and the header: all four situacion categories, `CAL140908936` twice in the same stage under two
different presumption oficios, a two-date cell, an Excel serial, two suppressed rows sharing an
oficio, and a row carrying cp1252-only bytes so the encoding test proves something.

Day-1 and day-2 assertions that changed: the format-1 record shapes in `test_diff.py` and
`test_catcfdi.py`, and the line in `test_cclasstrib.py` asserting `sat69b` was disabled.

### Nightly workflow

Each of the three enabled feeds is now its own step. The brief's first suggestion - one step per
feed with `continue-on-error: false` - cannot work, because that is the default and it stops the job
at the first failure: a SAT outage would throw away a good cClassTrib harvest. So each feed step
carries `continue-on-error: true`, the commit step runs on `always()` and commits whatever landed,
and a final gate step re-fails the job if any feed failed. The failed-run email still arrives, and
the day's good data is still saved.

### Day 4

1. **Package skeleton.** Publish `govdiff` to PyPI and a thin npm client, reusing the linejudge
   publishing path rather than inventing a second one. The Python side is nearly there -
   `pip install -e .` already works; what is missing is a versioned release, a changelog and the
   token wiring.
2. **A diff viewer on GitHub Pages.** The JSONL is now small enough to read in a browser, which was
   not true before today. Static page, no backend: pick a feed, pick two versions, render the
   records. This is the thing that makes the archive legible to somebody who is not going to clone
   it.
3. **Watch the 69-B `Last-Modified`.** It has said 22 January 2026 since the day-0 probe. The first
   time it moves is the first real diff this feed has ever produced anywhere, and it is worth
   checking that the run and the diff both behave when it does.

## 2026-09-07 - day 4

Three things that turn a repository full of Parquet files into something a person or a program can
use: a machine-readable index, two packages ready to publish, and a static viewer.

**No publisher was contacted today.** Every feed's data was already on disk. The only HTTP traffic
was to 127.0.0.1:8765 (a local static server) and 127.0.0.1:9222 (the VM's own Chrome).

### Part A: `govdiff index` and `docs/index.json`

One JSON file that says what the archive holds: every feed from `feeds.yaml` with its source
metadata, every stored version (id, date, row count, column count, sha256, Parquet path and byte
size), and every diff (from, to, JSONL path and byte size, summary path, and the summary's
added / changed / removed / unchanged counts and row totals). 15,176 B for 3 feeds, 13 versions
and 10 diffs. It is the only file the npm client or the viewer needs before it knows what exists.

Three decisions the rest of the day depends on:

1. **Every path is relative to the repository root**, not to `docs/`. On GitHub Pages the site root
   *is* `docs/`, so `diffs/` is not served there at all - a docs-relative path would be
   unresolvable in exactly the place the viewer runs. Repo-root paths join onto one base URL:
   `raw.githubusercontent.com/.../main/` on Pages, `../` on a local server started at the repo
   root. That is the whole resolution rule, and it is stated in the file as `path_base`.
2. **Nothing that moves on its own goes in the file.** `.state/<feed>.json` carries
   `last_fetched_at` and `last_result`, which change on every nightly run whether or not anything
   was published; including them would have produced a commit every single night that said
   nothing. Only `version_id`, `sha256`, `last_modified` and `row_count` are taken from `.state`.
3. **The writer leaves the file alone when only `generated_at` would have moved.** It builds the
   index, compares it with the committed one with the timestamp excluded, and rewrites only on a
   real difference. So `git status` after a quiet night is clean, and a touched `index.json` means
   the archive genuinely changed. Output is sorted keys, 2-space indent, trailing newline - the
   same shape as `meta.json` and the summaries.

Wired into `.github/workflows/nightly.yml` as a `Rebuild the archive index` step on `always()`,
between `Show status` and the commit, with `docs` added to that step's `git add`. On `always()` for
the same reason the commit step is: a feed that failed must not stop the index describing the feeds
that succeeded.

### Part B: the Python release path

Reused linejudge's publishing shape rather than inventing a second one.

- **`__version__` reads the installed package metadata** (`importlib.metadata.version`), falling
  back to `0.0.0+source` in a source tree that was never installed. The alternative - a constant in
  `__init__.py` kept in sync with `pyproject.toml` by hand - is what linejudge shipped, and the two
  copies are exactly the sort of thing that drifts silently: a version number that disagrees with
  what PyPI actually served is a small lie, and this project is meant to be the opposite of that.
  `pyproject.toml` is now the single source of truth and there is no second copy to disagree with
  it. `govdiff --version` prints it.
- **`CHANGELOG.md`** in Keep a Changelog form. 0.1.0 covers days 1-4 and is marked *unreleased*: it
  is built and tag-ready, and deliberately not published, because the archive it reads has to be
  public before a client that reads it is worth installing.
- **`MANIFEST.in` prunes `data`, `diffs`, `raw`, `docs`, `js`, `.state`, `.github` and `tests`.**
  The package is the tool; the repository is the archive. An sdist carrying `data/` and `diffs/`
  would ship tens of megabytes to everyone who runs `pip install govdiff`, and would grow every
  night. Checked, not assumed: the sdist is 43,902 B, and every entry in it is `src/govdiff/`,
  `pyproject.toml`, `README.md`, `CHANGELOG.md`, `LICENSE`, `requirements.txt` or `feeds.yaml`.
  The release workflow re-checks it and fails the release if any of those directories leaks in, so
  a future change cannot quietly reintroduce the problem.
- `python -m build` produces `govdiff-0.1.0.tar.gz` (43,902 B) and `govdiff-0.1.0-py3-none-any.whl`
  (44,394 B); `twine check dist/*` PASSED on both. `dist/` stays gitignored.
- **`.github/workflows/release.yml`**, triggered by pushing a `v*` tag: build, `twine check`, the
  sdist contents check, then publish to PyPI with `pypa/gh-action-pypi-publish` under
  `permissions: id-token: write` and environment `pypi`; then, only if PyPI succeeded, run the Node
  tests and `npm publish --provenance --access public`. **There is not one API token in this
  repository or in its secrets.** Both registries are published to with trusted publishing, so the
  credential that could leak does not exist. Nothing was tagged and nothing was published.

### Part C: the npm client

`js/`, package name `govdiff`, version 0.1.0, MIT, `"type": "module"`, `"engines": {"node":
">=18"}`, **zero dependencies** - Node's standard library and global `fetch`, nothing else.

Library: `listFeeds()`, `versions(feed)`, `diffs(feed)`, `latestDiff(feed)`, `summary(feed, from,
to)` and `readDiff(feed, from, to)` - the last an async iterator over the JSONL rather than an
array, because one catCFDI revision is 8,026 records and megabytes of text, and a caller who only
wants the additions should not have to hold the rest in memory. The response body is streamed and
split on newlines as it arrives. The index is fetched once per base URL per process.

CLI: `govdiff feeds`, `govdiff versions <feed>`, `govdiff latest <feed>` (prints the summary,
including the changed-fields histogram) and `govdiff diff <feed> <from> <to>` (streams JSONL to
stdout, so it pipes into `jq`). The version string is read out of `package.json` at runtime, for
the same reason the Python one is read out of package metadata.

Base URL is `https://raw.githubusercontent.com/phillipmex/latam-gov-diffs/main/`, overridable with
`GOVDIFF_BASE_URL` - which is also how the tests point it at a local server. `npm pack --dry-run`
shows five files (`index.js`, `cli.js`, `README.md`, `LICENSE`, `package.json`), 6.0 kB packed,
15.6 kB unpacked. `js/README.md` is short and points at the main README.

### Part D: the viewer

`docs/index.html` + `docs/viewer.js` + `docs/viewer.css` + `docs/.nojekyll`. Vanilla JavaScript,
HTML and CSS with **no build step and not one external request** - no CDN, no web font, no
analytics, and an inline SVG favicon so even the browser's automatic `/favicon.ico` request does
not 404. It works from a `file://` copy and under any Content-Security-Policy a reader cares to
apply.

Feed picker; version-pair picker defaulting to the newest diff; the summary as five counters plus
the changed-fields histogram and the added / dropped column lists; then the records - a filter box,
an op filter, 200 rows a page, and per record the key fields beside the changed fields as
before then after. Every view is a link: `#feed=cclasstrib&from=...&to=...`, and `&base=<url>`
overrides where the diff files are read from.

**The base-URL question, resolved rather than hand-waved.** Pages serves `docs/` as the site root,
so `diffs/` is not reachable from a Pages URL at all. The page always fetches `./index.json` from
beside itself, then resolves the repo-root-relative paths inside it against a base it detects:
`#base=` if given; otherwise `../` when the host is localhost over http (the page is at `/docs/`
and the archive is one level up); otherwise `raw_base_url` from `index.json`, which is the
raw.githubusercontent.com URL. Documented in the README, in the viewer's own header comment, and in
the error message the page shows if a diff file 404s.

**Big diffs.** The JSONL is streamed with `fetch` and a `ReadableStream` reader, decoded and split
line by line as chunks arrive. The first 5,000 records are parsed and kept for the table; past that
the lines are counted, not parsed, and the page says so in as many words. Day 3's format 2 had
already shrunk the catCFDI diff from 20.6 MB to 2.67 MB, so the cap was exercised against 8,026
records rather than the 20 MB the brief expected - the mechanism is identical and it is the reason
the page stays responsive on either.

### Verification in the browser

Served the repository root with `python -m http.server 8765 --bind 127.0.0.1` and drove the page in
the VM's own CDP Chrome (Chrome 152, `http://127.0.0.1:9222`; tab opened with `/json/new`, driven
over the DevTools protocol from a small Node 24 script using its built-in WebSocket client,
screenshotted with `Page.captureScreenshot`, tab closed afterwards). No package was installed for
this.

What was actually checked, not assumed:

| check | result |
|---|---|
| page loads; title and tagline | `latam-gov-diffs - diff viewer`; tagline exact |
| console and browser log | **zero entries** on the final run |
| feed picker | all three feeds |
| deep link `#feed=cclasstrib&from=2025-10-03-b5ed31f4&to=2025-11-24-431d4217` | honoured; pickers and summary match it |
| summary counters | 7 added / 25 changed / 4 removed / 113 unchanged; 142 rows to 145 |
| changed-fields histogram | `link`, `credito_para`, `dataatualizacao`, `indnfgas`, `indcteos`, ... |
| dropped columns | `credito_para`, with the note explaining why a dropped column makes every row read as changed |
| filter box | `dataatualizacao` narrows to 18 of 36 |
| op filter | `removed` narrows to 4 of 36; first row `cclasstrib=210001` |
| catCFDI, the big one | 8,026 of 8,026 counted, first 5,000 shown, the message says so, no freeze |
| paging | Next moves to records 201-400 |
| `sat69b` (one version, no diff) | explains that a diff needs two versions |
| `&base=` override | honoured, preserved in the hash, diff loads from the override |
| dark mode | rendered dark under the VM's system theme |

Pages was **not** enabled and the repository is still private, per the rules. The one branch that
cannot be tested until the public flip is the raw.githubusercontent.com base - it is the fallback
that runs when the host is not localhost, and the first thing to check on 09-22.

### Requests made

**None.** No government publisher was contacted today; nothing in day 4 needs to fetch. Total
external HTTP requests: zero.

### Tests

`pytest -q`: **105 passed** (92 from day 3, 13 new in `tests/test_index.py`). The new tests build a
miniature two-feed archive in a temp directory and check the index against it: feed metadata
straight from `feeds.yaml` including the disabled feed, versions oldest first with dates, row and
column counts and hashes, repo-root-relative paths with forward slashes on Windows too, diffs in
chain order carrying the summary counts, the deliberate absence of `last_fetched_at` and
`last_result` from the state block, the deterministic render, both CLI forms - and the two writer
behaviours that matter: the file is left byte-for-byte alone when only `generated_at` moved, and is
rewritten when a version appears. One test rebuilds the index against the real repository and
asserts the committed `docs/index.json` is what `govdiff index` produces today, so a stale index
fails the nightly run's own test step rather than shipping quietly.

`npm test` in `js/`: **20 passed**. They run against the real archive in this repository, served by
a throwaway `node:http` server the test starts, with `GOVDIFF_BASE_URL` pointed at it - not
`file://`, because global `fetch` refuses that scheme outright, which is the whole reason the
server exists. Covered: the index, feed metadata, versions oldest first, diffs forming an unbroken
chain, `latestDiff` returning null on a one-version feed, summary counts read from the real
`.summary.json`, `readDiff` yielding exactly added + changed + removed records with the right op
split, an early `break` leaving the rest unread, 2,000 records read across many chunk boundaries
out of the 2.67 MB catCFDI diff, the format-2 record shape, and four CLI paths including both error
exits.

### Defects and caveats

1. **`pip install govdiff` outside a clone will not find `feeds.yaml`.** `repo_root()` walks two
   directories up from the module, which is right in a source tree and points into `site-packages`
   in a wheel install. `GOVDIFF_ROOT` overrides it, so the tool works, but the default is wrong for
   the exact install the release path creates. Found today and deliberately not fixed today: it is
   a behaviour change to code day 4 was not asked to touch. Fix it before anything is tagged.
2. **Both packages install a binary called `govdiff`.** That is the point brand-wise and it is
   still a PATH collision for anyone who installs both - whichever came last wins. The Python one
   harvests, the Node one reads. Kept deliberately; worth one line in each README before launch.
3. **`govdiff --version` reports `0.0.0+source`** in a source tree that was never `pip install`ed.
   Honest rather than wrong, but it looks odd to somebody running from a clone.
4. **The histogram shows the top 25 columns** and says how many more there are. A feed that moved
   80 columns is summarised, not fully listed.
5. **npm trusted publishing may need one manual publish first** - see the launch-day table below.
   It is the single step most likely not to work first time.

### For the owner, on launch day

Register the two trusted publishers before pushing any tag. None of this can be done by an agent -
all of it needs the owner's own logged-in accounts.

| step | where | what to enter | min |
|---|---|---|--:|
| Create two environments | GitHub, repo Settings, Environments | names exactly `pypi` and `npm`; no secrets, no reviewers | 2 |
| PyPI pending publisher | pypi.org, Account, Publishing, add a *pending* publisher | project `govdiff`, owner `phillipmex`, repository `latam-gov-diffs`, workflow `release.yml`, environment `pypi` | 5 |
| npm trusted publisher | npmjs.com, the `govdiff` package, Settings, Trusted publisher | the same four values, environment `npm` | 5 |
| *only if npm refuses because the package does not exist yet* | a terminal | `cd js` then `npm publish --access public` once by hand (2FA prompt), then set the trusted publisher on the now-existing package and let the workflow do every release after | +5 |
| then | a terminal | `git tag v0.1.0` and `git push origin v0.1.0` | 1 |

**About 13 minutes, 18 if npm needs the manual first publish.** PyPI supports pending publishers
for projects that do not exist yet; npm configures trusted publishing on the package page, which is
why a brand-new npm name may have to exist first. Separately, at the public flip: make the
repository public and enable Pages from `main` and `/docs` - about 3 minutes, after which the
viewer is live at https://phillipmex.github.io/latam-gov-diffs/ with no further work.

### Day 5

1. **A change feed, generated by `govdiff index`.** It already walks every diff and every summary,
   so it is the natural place to also write an **Atom feed** (`docs/feed.xml`: one entry per diff,
   newest first, with the counts and a link straight into the viewer's deep link) and a rolling
   **`CHANGES.md`**. Both are derived files, both belong under the same
   deterministic-output-and-do-not-rewrite discipline as `index.json`, and both should come out of
   the same nightly step. An Atom feed is the one format a finance or compliance team can subscribe
   to without writing any code, and it is the cheapest thing on the list that turns a repository
   into a product.
2. **Finish the viewer.** It is legible but plain. The real gaps: no way to look at a *version*,
   only at a diff; no per-catalogue filter on catCFDI, where 25 catalogues share one table; no
   permalink to a single record; and the 5,000-record cap has no "load the next 5,000" escape.
3. **Fix `repo_root()` for a wheel install** (caveat 1 above) before anything is tagged. A
   published package whose first command fails outside a clone is a bad first impression, and the
   fix is small: fall back to the working directory, honour `GOVDIFF_ROOT`, and say so in the
   error.
4. **Watch the 69-B `Last-Modified`.** Still 22 January 2026, unchanged from the day-3 note. The
   first time it moves is the first real diff this feed has ever produced anywhere.

## 2026-09-07 - day 5 - the change feed, and a viewer that is finished

Day 4 left a repository that a program could read. Today it becomes something a person can
subscribe to: an Atom feed and a readable changelog written by the same command that writes the
index, a viewer with a front door instead of only a diff table, and the wheel-install defect closed
before anything is tagged.

**No publisher was contacted today.** Every byte was already on disk. The only HTTP traffic was to
127.0.0.1:8765 (a local static server), 127.0.0.1:9222 (the VM's own Chrome) and 127.0.0.1:9223 (a
second, throwaway Chrome - see the verification note). Total external requests: **zero**.

### Part A: where the archive lives

The day-4 defect, fixed first. `repo_root()` walks two directories up from the module. In a clone
that is the repository; in a wheel it is `site-packages`, so `pip install govdiff && govdiff
status` looked for `feeds.yaml` inside the installed package. The failure mode was worse than an
error message: a command that *writes* could have created a `data/` directory inside site-packages.

`config.resolve_repo_root(explicit)` is the fix, and it is four branches and nothing else:

1. `--repo PATH` (the global CLI option; `--root` is day 1-4's spelling and still lands in the same
   place),
2. `$GOVDIFF_REPO` (`$GOVDIFF_ROOT` is honoured as an alias, because that is what day 4 documented),
3. the current working directory, if it holds `feeds.yaml`,
4. otherwise `RepoNotFound`, whose message names `git clone`, `--repo`, `GOVDIFF_REPO` **and the
   directory it actually tried**.

Two decisions inside that:

- **`repo_root()` is deliberately not in the chain.** It is tempting - it would make a source-tree
  checkout work from anywhere - but it is exactly the guess that caused the defect, and including
  it would make branch 4 untestable from a source tree. `repo_root()` itself is untouched: it is
  still what `load_feeds()` and the library callers use, and one test asserts it still answers the
  source-tree question correctly.
- **A wrong `--repo` or a wrong `GOVDIFF_REPO` is an error, not a fall-through.** If someone says
  where the archive is and is wrong about it, silently harvesting into a different directory is the
  worst possible outcome. Say so and stop.

All five commands now start with `resolve_repo_root(args.root)`. Ten tests in
`tests/test_repo_resolution.py` cover all four branches, both env spellings, both flag spellings,
the "package directory is not a fallback" case, and the CLI's exit code 1 with `no archive found`
on stderr.

### Part B: the change feed

`src/govdiff/changefeed.py`, written by `govdiff index` - **the same command, the same walk of the
archive, the same nightly step.** No new workflow step, because a second step is a second thing
that can fail on its own and a second commit that can race the first.

Five files come out of it:

| file | bytes | what |
|---|--:|---|
| `docs/feed.xml` | 13,778 | Atom 1.0, all 10 diffs across all feeds, newest first |
| `docs/cclasstrib/feed.xml` | 12,865 | the same, one feed |
| `docs/catcfdi/feed.xml` | 1,791 | " |
| `docs/sat69b/feed.xml` | 843 | " - no entries yet, and written anyway |
| `CHANGES.md` | 4,215 | the same history as a table, for reading |

One entry per published revision. The title carries the counts the way a reader sees them in a
list - `cclasstrib 2026-04-15 -> 2026-06-23: +8 / ~156 / -0` - because an Atom reader shows titles
and hides everything else until you click. The content is plain text: the four counts, the row
total before and after, the top five columns that moved with their record counts, any column the
publisher added or dropped, the diff file and its size, and the publisher's name. Two links:
`rel="alternate"` is the viewer deep link (`.../#feed=...&from=...&to=...`), `rel="enclosure"` is
the raw `.jsonl` on raw.githubusercontent.com with its byte length, so a reader can hand the file
straight to a script.

The decisions worth recording:

1. **`updated` is the newest diff's `generated_at`, never `now()`.** This is the whole reason the
   file can be committed. A feed stamped with the time of writing changes every night, produces a
   commit every night, and tells every subscriber that something happened when nothing did. Taking
   the timestamp from the data means a quiet night rewrites nothing at all - and `_write_if_changed`
   compares bytes, so the committed file is only touched when the archive really moved. Verified by
   running `govdiff index` twice: the second run prints `unchanged, left alone`.
2. **Entry ids are RFC 4151 tag URIs** built from feed, from-version and to-version -
   `tag:phillipmex.github.io,2026:latam-gov-diffs/cclasstrib/<from>__<to>`. They do not contain a
   date of generation and they do not change if the file is rewritten, so no reader ever shows the
   same change twice. A `tag:` URI is also the correct thing here rather than a URL: the id is an
   identity, not a location, and the location is already in the two `link` elements.
3. **The `generator` element carries no version number.** It would be the one field that differs
   between a clone (`0.0.0+source`) and a wheel (`0.1.0`), which would make the file's bytes depend
   on how the tool was installed. Byte-stability wins over a nicety.
4. **`build_entries` reads the `.summary.json` files directly** rather than widening
   `docs/index.json`. The feed needs each diff's `generated_at` and `changed_fields`; the index
   carries neither, on purpose - it is a description of what exists, not of what moved. Adding them
   would have changed the index's shape and its do-not-rewrite comparison on day 5 of its life.
5. **An empty feed still gets a file.** `sat69b` has one version and no diff, so its Atom has no
   entries and its `updated` falls back to the newest archived version's date at midnight UTC. The
   alternative is the overview page's subscribe link 404ing for the one feed most likely to matter
   first.
6. **`--output` skips the change feed**, and there is a `--no-change-feed` flag for the same
   purpose. `--output` means "write the index somewhere else"; it must not have the side effect of
   writing five files into the repository.

`CHANGES.md` is a section per feed with the source line, the key fields, the version span and a
reverse-chronological table: published date, from-version to to-version, the three counts, the top
three columns that moved, and a link to the `.jsonl`. Its header says **generated by `govdiff
index`, do not edit**, because the first thing anyone does with a file called CHANGES.md is edit it.

`nightly.yml`'s commit step now reads `git add -A data diffs .state raw docs CHANGES.md`. `docs/`
was already covered; `CHANGES.md` sits at the repository root and was not.

### Part C: the viewer, finished

Three states, all addressable, all in the same three files with no build step and still not one
external request:

- **no hash** - the three feeds as cards (publisher, country, title, versions archived, the latest
  change's counts and date), a subscribe panel pointing at `feed.xml` and `CHANGES.md`, and a
  four-row *How to use it* block: read it in a browser, poll it from a script (with the actual raw
  URL, marked *no install*), `pip install govdiff` and `npm install govdiff` (both marked
  *available from launch*, which is the honest label until 09-22).
- **`#feed=<id>`** - the source: publisher, country, a link to the published document, the listing
  page, key fields, format, versions archived, first and latest version dates with the row count,
  and changes recorded. Beside it the subscribe links for that feed and for all feeds. Then the
  timeline: every diff, newest first, each row a deep link showing the date, the version span, the
  three counts and the file size.
- **`#feed=<id>&from=...&to=...`** - the diff view from day 4, plus a **Copy link** button, a
  **Download JSONL** link to the raw file with its size in the tooltip, and a *Changed fields* block
  that is now sortable by count or by name. The record key is rendered as the largest thing in its
  row rather than one label among many, since it is the first thing anyone looks for.

Decisions:

- **Routing is `readHash()` and `hashFor()`, and nothing else.** Every link on the page is built by
  `hashFor`, which carries an existing `&base=` override through every navigation, so a reader
  pointed at a fork stays pointed at it. Navigation is *setting the hash*; a single `hashchange`
  listener does the rendering. That means the back button works everywhere for free, and there is
  one code path whether you arrived from a bookmark, from the Atom feed, or by clicking.
- **A feed with no diff routes to its overview, not to an empty table.** Picking `sat69b` in the
  feed picker lands on the overview, which explains that a diff needs two versions.
- **Copy link degrades rather than throwing.** The async clipboard needs a focused document and a
  secure context; when it is unavailable the button falls back to a hidden textarea, and if that
  fails too it says *Copy failed - use the address bar*. Never a console error.
- Every existing function name, the 5,000-record cap, the streaming reader and the base-URL
  resolution from day 4 are unchanged. The new code is around them, not through them.
- Below 720 px everything is one column: the panels, the feed cards, the pickers, the detail grids
  and the timeline rows. Verified as zero horizontal overflow at 390 px, not eyeballed.

### Verification in the browser

Served the repository root with `python -m http.server 8765 --bind 127.0.0.1` and drove the page
over CDP in the VM's own Chrome 152 at 127.0.0.1:9222 - home, both overviews, the newest cclasstrib
diff, the big catCFDI diff, the filter, the op filter, paging, the sort chips, copy link, dark mode
and a 390 px viewport. Everything rendered correctly.

**The console was not clean, and the reason is worth writing down.** Five errors appeared, all of
the form *"the message port closed before a response was received"*, one of them naming
`chrome-extension://.../kwift.CHROME.js`. That profile is the owner's daily browser: it has
extensions, and one of them is Dark Reader, which is also why `getComputedStyle(body)` returned
pure black in both light and dark - the extension was repainting the page, so the theme could not
be verified there at all.

So the run was repeated in a second Chrome started with a throwaway profile,
`--headless=new --disable-extensions`, on port 9223. Same binary, same VM, no extensions:

| check | result |
|---|---|
| console and browser log, all three states | **zero errors, zero warnings** |
| home | 3 feed cards, correct counts and dates, raw URL rendered |
| overview `cclasstrib` | 9 timeline rows, first one 2026-06-23, +8 ~156 -0, 201 kB; all metadata present |
| overview `sat69b` | explains that a diff needs two versions |
| diff, newest `cclasstrib` | 164 records, 17 changed-field bars, key `cclasstrib 221002` |
| sort chips | by count then by name; by name gives `dataatualizacao, descricao_cclasstrib, dfimvig` |
| filter | `aliquota` narrows to 8 of 164 |
| catCFDI, the big one | 8,026 counted, first 5,000 loaded, 200 shown, the notice says so |
| Copy link | copies the full deep link, button says *Link copied* |
| light theme | body `rgb(255,255,255)`, panel `rgb(246,247,248)` |
| dark theme | body `rgb(20,23,26)`, ink `rgb(230,233,236)`, link `rgb(121,176,240)` |
| 390 px, overview and home | 0 px horizontal overflow; panels and cards single column |

Both browsers' tabs were closed and both servers stopped. Pages was not enabled and the repository
is still private.

### Requests made

**None.** No government publisher was contacted. External HTTP requests: zero. Local only:
`127.0.0.1:8765` (static server), `127.0.0.1:9222` and `127.0.0.1:9223` (Chrome DevTools).

### Tests

`pytest -q`: **135 passed**, up from 105. Thirty new:

- `tests/test_repo_resolution.py` (10) - the four branches, both env spellings, both flag
  spellings, a bad `--repo` and a bad `GOVDIFF_REPO` each raising rather than falling through, the
  package directory not being a fallback, and the CLI's exit code and stderr.
- `tests/test_changefeed.py` (20) - the Atom output parsed with `xml.etree.ElementTree` and checked
  for well-formedness and every required element; entry titles, ids, both link hrefs and the
  content text; `updated` equal to the newest diff's timestamp and not to `now()`; per-feed
  filtering; the empty-feed case; XML escaping of angle brackets and ampersands in a field name;
  `CHANGES.md`'s header, sections, ordering and *+1 more* truncation; **determinism** -
  `write_change_feed` run twice produces identical bytes and reports nothing written the second
  time; a new diff appearing does rewrite it; the CLI integration; and both escape hatches. Plus
  `test_the_committed_change_feed_is_current`, which regenerates against the real repository and
  fails if what is committed is stale - the same guard `docs/index.json` has had since day 4.

`npm test` in `js/`: **20 passed**, unchanged. The Node client reads `index.json` and the diffs and
is untouched by today's work.

### Defects and caveats

1. **The Atom feed's entry order is by `to` version, then `from`, then feed id - not by wall
   clock.** Two publishers releasing on the same date sort by feed name, which is arbitrary but
   stable. Stable matters more than clever here.
2. **`CHANGES.md` grows without bound.** 10 changes today, 4.2 kB. At a few revisions a month per
   feed it is years away from being a problem, but there is no truncation and no archive split.
3. **The changed-fields bar list still shows the top 25** and says how many more there are. Day 4's
   caveat, unchanged.
4. **Both packages still install a binary called `govdiff`.** Day 4's caveat 2, unchanged.
5. **`govdiff --version` still reports `0.0.0+source`** from a clone. Day 4's caveat 3, unchanged,
   and now load-bearing: it is why the Atom `generator` carries no version.
6. **The raw.githubusercontent.com base URL is still untested in anger.** It is the branch the
   viewer takes on Pages, and it cannot run until the repository is public. First thing to check on
   09-22.
7. **The 69-B `Last-Modified` is still 22 January 2026.** Unmoved since day 3.

### Day 6

Three offer pages and a README polish. What matters is that nothing on them can be a claim the
archive does not support, so here is exactly what it supports as of tonight:

| feed | versions | span | diffs | latest row count | records moved (added / changed / removed) |
|---|--:|---|--:|--:|---|
| `cclasstrib` | 10 | 2024-12-07 to 2026-06-23 | 9 | 164 | 88 / 837 / 18 |
| `catcfdi` | 2 | 2024-12-04 to 2026-09-03 | 1 | 362,345 | 7,917 / 108 / 1 |
| `sat69b` | 1 | 2026-01-22 | 0 | 14,234 | none yet |
| **total** | **13** | | **10** | | |

1. **`docs/offers/cclasstrib.html`, about $28/mo.** Truthfully: 10 archived versions over 18
   months, 9 diffs, the full IBS/CBS classification table at 164 rows, and a record-level history
   of every revision that the NF-e portal does not publish anywhere. Do **not** claim the raw
   versions are exclusive - the portal keeps its dated releases and anyone can re-download them.
   The diff history is the product.
2. **`docs/offers/catalogos-sat.html`, $39/mo.** 25 catalogues, 362,345 rows, one revision recorded
   so far (7,917 additions, 108 changes, 1 removal, 2024-12-04 to 2026-09-03) with the columns that
   moved named. One diff is a thin claim; lead with the coverage and the format, and say plainly
   that the change history starts here. The honest hook is that SAT links only the current
   workbook, so nobody who has not been recording has this.
3. **`docs/offers/listas-mx.html`, $99/mo plus a $250 point-in-time attestation.** This is the one
   with the real moat and the weakest archive: 14,234 rows, one snapshot, **zero diffs**, and
   history that starts 2026-09-07 because SAT publishes the current list only. Say that out loud -
   it is the argument, not the weakness. The attestation product is "on date D, RFC X stood at
   stage Y in the list as published", which the archive can already answer for every day it has
   been running. It cannot answer it for any day before 2026-09-07, and the page must not imply
   otherwise.
4. **Stripe links do not exist yet** and are the owner's hand, expected around 09-19. Every page
   needs one clearly marked placeholder - a disabled button reading something like *Checkout opens
   2026-09-22* with an HTML comment naming the exact attribute to paste the link into - so the
   owner's job on the day is a find-and-replace and nothing else. Do not create a Stripe account, a
   payment link, or anything resembling one.
5. **Wire the nav.** `docs/index.html`'s *Paid feeds* link points at the README today; it becomes
   the offer index once the pages exist.
6. **README polish.** The Feeds table should carry the version and diff counts, and the "honest
   note on the moat" already says the right thing - keep it, and make sure the offer pages agree
   with it word for word rather than overselling.
