# latam-gov-diffs

A nightly archive and **machine-readable change feed** for Latin American government reference data.

Governments publish these tables as spreadsheets and quietly restructure them. This repository fetches
each source, stores a dated snapshot as Parquet, and commits a record-level diff against the previous
version. The diff, not the file, is the product.

## Feeds

| id | source | status | versions | diffs |
|---|---|---|---:|---:|
| `cclasstrib` | Brazil, Portal Nacional da NF-e - IBS/CBS tax classification table | **live** | 10 | 9 |
| `catcfdi` | Mexico, SAT - CFDI 4.0 catalogues (Anexo 20) | **live** | 2 | 1 |
| `sat69b` | Mexico, SAT - Listado completo 69-B | **live** | 1 | 0 |

The version and diff counts are the ones in [`docs/index.json`](docs/index.json) as committed; they
grow on any night a publisher moves, and that file - not this table - is the machine-readable
answer. `sat69b` has one snapshot and no diff because SAT has not republished the list since the
archive's first fetch on 2026-09-07.

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

## Paid feeds

The archive, the viewer, the change feed and both clients are free and stay free. Four things are
sold on top of them, and nothing is on sale before **2026-09-22**:

| product | feed | price (USD) |
|---|---|---|
| `cclasstrib` feed | `cclasstrib` | [$28 / month](docs/offers/cclasstrib.html) |
| `catalogos-sat` feed | `catcfdi` | [$39 / month](docs/offers/catalogos-sat.html) |
| `listas-mx` feed | `sat69b` | [$99 / month](docs/offers/listas-mx.html) |
| `listas-mx` point-in-time attestation | `sat69b` | [$250 one-off](docs/offers/listas-mx.html#attestation) |

Each price links to that product's offer page. Nothing is on sale before 2026-09-22: every buy
button points at a `#stripe-pending` placeholder and says so.

A paid feed is an invite to a **private GitHub repository** carrying the same nightly diff stream
for one output, committed there twelve hours before the public archive, with GitHub's own
notifications as the alert, a `changes.json` written for machines, and support by GitHub issue
answered within two business days. No hosted API, no webhooks, no SLA. The attestation is a
written, printable statement of whether one RFC appeared on the SAT 69-B list on a given date,
with the snapshot ids, their sha256 and the SAT document URL and `Last-Modified` at the time -
produced by `govdiff attest`, and not legal advice.

**[docs/paid.md](docs/paid.md) is the full and binding description**: delivery, what is explicitly
not included, the attestation's coverage limit, fulfilment and refunds. The offer pages are in
[docs/offers/](docs/offers/).

## Install

Both clients are **available from launch, 2026-09-22**. Nothing is on PyPI or npm before then.

```
pip install govdiff      # the harvester: fetch, snapshot, diff, index
npm install govdiff      # a zero-dependency Node reader for the published archive
npx govdiff feeds        # or just read it, no install
```

The Python package is the tool that fills this archive; the npm package only reads it, over
plain HTTPS, with no key and no account. `js/README.md` documents the Node side.

## Viewer

<https://phillipmex.github.io/latam-gov-diffs/> - a static page in `docs/`: pick a feed, pick two
versions, read what moved. Vanilla JavaScript, no build step, and not one external script, font or
analytics call, so it works offline and under any Content-Security-Policy.

It reads `index.json` from beside itself and the diff files from wherever the archive is. On
GitHub Pages the site root **is** `docs/`, so `diffs/` is not served there at all and the page
fetches diff files from `https://raw.githubusercontent.com/phillipmex/latam-gov-diffs/main/`
instead. Running it locally, start the server at the repository root so that `../diffs/` resolves:

```
python -m http.server 8765          # from the repository root
# then open http://127.0.0.1:8765/docs/
```

Every view is a link, so any of them can be bookmarked, pasted into a ticket, or arrived at from
the change feed:

| address | what you get |
|---|---|
| no hash | the three feeds as cards, with the latest change on each, and how to read the archive |
| `#feed=cclasstrib` | the feed's source details and every change it has recorded, newest first |
| `#feed=cclasstrib&from=<version>&to=<version>` | one change, record by record |

Add `&base=<url>` to any of them to point the page at a fork or a mirror. The diff view has a
**Copy link** button and a **Download JSONL** link to the raw file, a *Changed fields* bar list
sortable by count or by name, and a filter across every value. A diff of any size streams as it
downloads; the table shows the first 5,000 records and says how many more it counted but did not
load. Mouse-only throughout, and one column below 720 px.

## Running it from source

```
pip install -r requirements.txt && pip install -e .
govdiff status                   # feeds, version count, last fetch, last result
govdiff run cclasstrib           # fetch, snapshot if changed, diff vs previous
govdiff run                      # every enabled feed
govdiff bootstrap cclasstrib     # load the publisher's whole back catalogue
govdiff bootstrap catcfdi        # same, for any feed whose parser lists versions
govdiff rediff cclasstrib        # rebuild every diff from the stored snapshots, no network
govdiff index                    # rebuild docs/index.json, the Atom feeds and CHANGES.md
govdiff attest sat69b --rfc <RFC> --on 2026-09-22        # point-in-time statement, no network
govdiff attest sat69b --rfc <RFC> --between A B          # ... across a span of dates
```

`attest` writes the Markdown document described in [docs/paid.md](docs/paid.md): whether the RFC
appeared on the 69-B list on that date, the `situacion`, the oficio numbers, and the snapshot
version ids with their sha256, the SAT document URL and the `Last-Modified` SAT reported at the
time. It reads the stored snapshots only and makes no request. It refuses any date outside what
the archive observed rather than inferring one, and it is offered for `sat69b` alone - the other
publishers keep dated back-versions, so a statement about them is reproducible from the source.

**Every command needs to know which checkout it is working on**, and looks in three places, in
order: the `--repo PATH` option, the `GOVDIFF_REPO` environment variable, then the current
directory if it holds `feeds.yaml`. If none of those answers, it says so and names all three
rather than guessing. `--root` is the old spelling of `--repo` and still works, as does
`GOVDIFF_ROOT`.

```
govdiff --repo /srv/latam-gov-diffs status     # say where the archive is
export GOVDIFF_REPO=/srv/latam-gov-diffs       # or say it once
cd /srv/latam-gov-diffs && govdiff status      # or just stand in it
```

This matters for `pip install govdiff`: the wheel has no archive inside it, so a bare `govdiff
status` outside a clone is an error with instructions, not a crash or a stray directory written
into site-packages.

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

## The archive index

`docs/index.json` is the machine-readable description of everything in here, rebuilt by
`govdiff index` at the end of every nightly run. It is the only file a reader needs before it
knows what exists - the npm client and the viewer both start there.

```json
{
  "format": 1,
  "generated_at": "2026-09-07T07:04:06+00:00",
  "raw_base_url": "https://raw.githubusercontent.com/phillipmex/latam-gov-diffs/main/",
  "path_base": "repository-root",
  "feed_count": 3,
  "feeds": [
    {
      "id": "cclasstrib", "title": "...", "country": "BR", "publisher": "...",
      "key_fields": ["cclasstrib"], "document_url": "...", "listing_url": "...",
      "version_count": 10, "diff_count": 9, "latest_version": "2026-06-23-1448cb63",
      "state": { "version_id": "...", "sha256": "...", "last_modified": null, "row_count": 164 },
      "versions": [
        { "version_id": "2024-12-07-67a71e9a", "date": "2024-12-07", "row_count": 94,
          "column_count": 8, "sha256": "...", "source_url": "...",
          "parquet": "data/cclasstrib/2024-12-07-67a71e9a/data.parquet", "parquet_bytes": 4242,
          "meta": "data/cclasstrib/2024-12-07-67a71e9a/meta.json" }
      ],
      "diffs": [
        { "from": "...", "to": "...", "format": 2,
          "jsonl": "diffs/cclasstrib/<from>__<to>.jsonl", "jsonl_bytes": 118613,
          "summary": "diffs/cclasstrib/<from>__<to>.summary.json",
          "added": 7, "changed": 25, "removed": 4, "unchanged": 113,
          "rows_from": 142, "rows_to": 145 }
      ]
    }
  ]
}
```

Three things are guaranteed. **Every path is relative to the repository root**, never to `docs/`,
so a reader joins it onto one base URL and is done. **Versions are oldest first and diffs are in
chain order**, each diff starting where the last one ended. **The file is deterministic** - sorted
keys, two-space indent, trailing newline - and it is left byte-for-byte alone when only its own
`generated_at` would have moved, so a nightly commit touching it means the archive really changed.
That is also why nothing timing-related from `.state/` is in it: `last_fetched_at` moves every
night whether or not anything happened.

## Change feed

`govdiff index` writes the same history in two more shapes, from the same walk of the archive and
in the same nightly step. Nothing here needs a build, an account, or a key.

| file | what it is |
|---|---|
| [`docs/feed.xml`](https://phillipmex.github.io/latam-gov-diffs/feed.xml) | Atom 1.0, every change across all feeds, newest first |
| `docs/<feed>/feed.xml` | the same for one feed - e.g. `docs/cclasstrib/feed.xml` |
| [`CHANGES.md`](CHANGES.md) | the same history as a table, one section per feed, for reading |

**In a feed reader**, subscribe to
`https://phillipmex.github.io/latam-gov-diffs/feed.xml` for everything, or
`https://phillipmex.github.io/latam-gov-diffs/cclasstrib/feed.xml` for one source. The viewer
page also advertises the feed with `<link rel="alternate">`, so a reader extension offers it when
you are looking at the page.

Each entry is one published revision. The title carries the counts
(`cclasstrib 2026-04-15 → 2026-06-23: +8 / ~156 / −0`), the content is a plain-text summary
naming the columns that moved and any column the publisher added or dropped, and there are two
links: `rel="alternate"` opens that change in the viewer, `rel="enclosure"` is the raw `.jsonl`
on `raw.githubusercontent.com`. Entry ids are stable
[tag URIs](https://www.rfc-editor.org/rfc/rfc4151) built from feed, from-version and to-version,
so a reader never shows the same change twice.

**From a script**, poll the feed and stop at the first id you have already seen:

```
curl -s https://phillipmex.github.io/latam-gov-diffs/feed.xml
```

The feed's own `updated` is the newest diff's generation time, **not** the time the file was
written. So a night that harvested nothing produces a byte-identical file, no commit, and no
false "something changed" in anyone's reader. Polling once a day is plenty; the sources publish
every few weeks at best.

## Releasing

One tag does everything. Bump the version in `pyproject.toml` and `js/package.json`, move the
`CHANGELOG.md` entry out of unreleased, then push `vX.Y.Z`: `.github/workflows/release.yml` builds
the sdist and wheel, runs `twine check`, refuses the release if `data/`, `diffs/`, `raw/`, `docs/`
or `js/` leaked into the sdist, publishes to PyPI, and then - only if PyPI succeeded - runs the
Node tests and publishes the npm package with `--provenance`. There are no API tokens in the
repository or in its secrets: both registries use **trusted publishing**, where the job proves who
it is with a short-lived OIDC token and the registry checks it against a publisher the owner
registered by hand (environments `pypi` and `npm`). `govdiff --version` reads the installed
package metadata, so `pyproject.toml` is the only place the Python version number is written.


## Ground rules

Plain unauthenticated GETs with a browser User-Agent, 40 s timeout, one retry. A 403/429/503 or a
challenge page raises `SourceChallenged` and the run stops - no proxy, no renderer, no bypass. Snapshots
are written only when the content hash or `Last-Modified` changes.

Code is MIT. The archived data is public government data, reproduced with attribution - see `LICENSE`.
