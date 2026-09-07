# latam-gov-diffs

A nightly archive and **machine-readable change feed** for Latin American government reference data.

Governments publish these tables as spreadsheets and quietly restructure them. This repository fetches
each source, stores a dated snapshot as Parquet, and commits a record-level diff against the previous
version. The diff, not the file, is the product.

## Feeds

| id | source | status |
|---|---|---|
| `cclasstrib` | Brazil, Portal Nacional da NF-e - IBS/CBS tax classification table | **live** |
| `catcfdi` | Mexico, SAT - CFDI 4.0 catalogues (Anexo 20) | registered, no parser yet |
| `sat69b` | Mexico, SAT - Listado completo 69-B | registered, no parser yet |

Only `cclasstrib` is live today. The other two are stubs in `feeds.yaml` with their probed URLs.

## Honest note on the moat

The NF-e portal and the SAT catalogue tree both keep dated back-versions online, so the raw history here
is reproducible by anyone. What is not published anywhere is the **per-revision diff**: which
classification codes were added, which fields changed, and when. That change history - and the change
feed built on it - is what this project makes. Only the SAT 69-B list is genuinely unbackfillable: the
publisher keeps the current snapshot only, so every day not archived is lost.

## Running it

```
pip install -r requirements.txt && pip install -e .
govdiff status                   # feeds, version count, last fetch, last result
govdiff run cclasstrib           # fetch, snapshot if changed, diff vs previous
govdiff run                      # every enabled feed
govdiff bootstrap cclasstrib     # load the publisher's whole back catalogue
```

`data/<feed>/<version>/` holds `data.parquet` plus a `meta.json` sidecar (schema, source URL, fetch time,
`Last-Modified`, sha256, row count). `diffs/<feed>/<from>__<to>.jsonl` holds one JSON object per changed
record, with a `.summary.json` beside it. `raw/` keeps source files up to 2 MB for provenance.

## Ground rules

Plain unauthenticated GETs with a browser User-Agent, 40 s timeout, one retry. A 403/429/503 or a
challenge page raises `SourceChallenged` and the run stops - no proxy, no renderer, no bypass. Snapshots
are written only when the content hash or `Last-Modified` changes.

Code is MIT. The archived data is public government data, reproduced with attribution - see `LICENSE`.
