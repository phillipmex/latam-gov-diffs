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
