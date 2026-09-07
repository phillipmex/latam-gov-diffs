# Changelog

All notable changes to `govdiff` are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versions follow
[Semantic Versioning](https://semver.org/).

This file covers the Python package. The npm client `govdiff` in `js/` tracks
the same version number and the same entries.

## [Unreleased]

Nothing yet.

## [0.1.0] - unreleased

The first release. **Built, tested and tagged-ready, but deliberately not
published**: the repository is private until 2026-09-22, and the archive it
serves has to be public before the client that reads it is worth installing.
Nothing here has been uploaded to PyPI or npm.

### Added

- **Fetcher** - one plain unauthenticated GET per URL, browser User-Agent, 40 s
  timeout, a single retry and only for a transport fault. Conditional requests
  from a committed `.state/<feed>.json`. A 403/429/503 or a challenge marker in
  a textual body raises `SourceChallenged` and stops the run; there is no bypass
  path in the code.
- **Snapshots** - `data/<feed>/<version>/data.parquet` plus a `meta.json`
  sidecar (schema, source URL, fetch time, `Last-Modified`, sha256, row count).
  Version ids are `<date>-<sha256[:8]>`; a content hash that is already stored
  never produces a second version. Source files at or below 2 MB are kept under
  `raw/` for provenance, larger ones are parsed in memory and discarded.
- **Record-level differ**, format 2 - `diffs/<feed>/<from>__<to>.jsonl` carries
  one object per changed record and only what moved, with a `.summary.json`
  beside it holding the counts, the schema drift and a `changed_fields`
  histogram.
- **Three feed adapters** - `cclasstrib` (Brazil, Portal Nacional da NF-e,
  IBS/CBS tax classification table), `catcfdi` (Mexico, SAT, the 25 CFDI 4.0
  catalogues of Anexo 20 in one keyed frame) and `sat69b` (Mexico, SAT, the
  Article 69-B list).
- **CLI** - `govdiff run`, `bootstrap`, `rediff`, `index`, `attest`, `status`,
  and `govdiff --version`.
- **`govdiff attest sat69b --rfc RFC --on DATE`** (and `--between FROM TO`) -
  a point-in-time attestation built from the archived snapshots and nothing
  else: whether the RFC appeared on the SAT 69-B list on that date, the
  `situacion`, every oficio number and publication date on both the SAT and the
  DOF side, and the evidence behind the answer - snapshot version ids, their
  sha256, the SAT document URL, the `Last-Modified` SAT reported at the time,
  and the next observation, so the edge of the evidence is visible rather than
  implied. Zero network. Coverage runs from the first archived snapshot to the
  last night the list was observed, and a date outside it raises
  `AttestationNotPossible` with the reason rather than an inference. Offered for
  `sat69b` alone; the other publishers keep dated back-versions, so a statement
  about them is reproducible from the source.
- **`govdiff index`** - writes `docs/index.json`, the machine-readable
  description of every feed, version and diff in the archive. Deterministic:
  sorted keys, two-space indent, and the file is left untouched when only its
  own timestamp would have moved.
- **Nightly GitHub Actions workflow** - one step per feed, each allowed to fail
  on its own so one publisher's outage cannot discard another's good harvest;
  the commit step runs regardless and a final gate re-fails the job so the
  owner still gets the failed-run email.
- **npm client** - a zero-dependency Node 18+ package that reads the published
  archive over HTTPS: `listFeeds`, `versions`, `diffs`, `latestDiff`,
  `readDiff` (an async iterator over the JSONL) and `summary`, plus a
  `govdiff feeds|versions|latest|diff` command line.
- **Static diff viewer** - `docs/index.html`, ready for GitHub Pages, with no
  build step, no external scripts and no fonts to fetch. Three states, all
  addressable: the feed cards and how-to-read block at no hash, a feed overview
  with the source details and every recorded change at `#feed=<id>`, and one
  change record-by-record at `#feed=<id>&from=<version>&to=<version>`. The diff
  view adds a copy-link button, a download link to the raw JSONL, and a
  changed-fields bar list sortable by count or by name; it keeps the 5,000
  record cap and says how many records it counted past it. One column below
  720 px, and nothing needs a keyboard.
- **Atom change feed** - `govdiff index` also writes `docs/feed.xml` (every
  change across all feeds, newest first), a per-feed `docs/<feed>/feed.xml`, and
  `CHANGES.md`, the same history as a readable table. One entry per published
  revision, with stable RFC 4151 tag ids, a viewer deep link, an enclosure
  pointing at the raw `.jsonl`, and a plain-text summary naming the columns that
  moved. The feed's `updated` is the newest diff's timestamp rather than the
  time of writing, so a night with no change rewrites nothing.
- **`--repo PATH`** on every command, with `GOVDIFF_REPO` in the environment and
  the current directory as the two fallbacks.
- **Paid-tier mechanics, written down** - `docs/paid.md`: the four fixed prices,
  what a paid feed is (a private GitHub repository, the diffs committed there
  twelve hours before the public archive, GitHub's own notifications as the
  alert, a per-feed `changes.json` for machines, support by issue answered
  within two business days), a plain list of what is *not* included, the $250
  attestation with its 2026-09-07 coverage floor and its not-legal-advice
  disclaimer, the operator's fulfilment steps, the refund line, and the
  `#stripe-pending` checkout placeholder convention. Linked from the README.
- **Offer pages** - `docs/offers/`: `offer.css` extending the viewer's tokens
  (light and dark, one column below 720 px, zero external requests),
  `TEMPLATE.md` documenting the structure every page copies, an index of the
  three outputs with their prices, and the `cclasstrib` page. Proof numbers are
  baked into the HTML and refreshed from `docs/index.json` at render time, so
  the page reads correctly with JavaScript off. The viewer's *Paid feeds* link
  now points at them.
- **`tests/test_docs_links.py`** - walks `docs/**/*.html`, asserts every
  relative link resolves to a file inside the repository, and fails if any page
  fetches a script, stylesheet, font, image or frame off its own origin.

### Fixed

- **The archive root is resolved, not guessed.** `repo_root()` walks up from the
  installed module, which is correct in a clone and points into site-packages
  from a wheel - so `pip install govdiff && govdiff status` looked for
  `feeds.yaml` inside the package. Commands now resolve the checkout from
  `--repo`, then `GOVDIFF_REPO`, then the working directory when it holds
  `feeds.yaml`, and otherwise fail with a message naming all three and the
  directory they tried. The package directory is never a fallback, and a
  `--repo` or `GOVDIFF_REPO` that points at the wrong place is an error rather
  than a silent fall-through. `repo_root()` itself is unchanged.

### Notes

- `__version__` is read from the installed package metadata, so `pyproject.toml`
  is the single source of truth and a source tree that was never installed says
  `0.0.0+source` rather than guessing.
- The sdist contains the tool only. `data/`, `diffs/`, `raw/`, `docs/` and
  `.state/` are pruned: they are the repository's product, not the package's.
