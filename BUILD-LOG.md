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
