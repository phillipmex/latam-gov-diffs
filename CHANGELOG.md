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
  `TEMPLATE.md` documenting the structure every page copies, and an index
  listing all four products with their prices and linking each to its page.
  One page per product: `cclasstrib.html` ($28/mo), `catalogos-sat.html`
  ($39/mo) and `listas-mx.html` ($99/mo), the last carrying the $250
  point-in-time attestation as a second product block with its own price, its
  own placeholder button and a real `govdiff attest` document rendered against
  the committed archive for a synthetic RFC that is not on the list. Proof
  numbers are baked into the HTML and refreshed from `docs/index.json` at render
  time, so every page reads correctly with JavaScript off. The viewer's *Paid
  feeds* link now points at them, and the README links each price to its page.
- **`tests/test_docs_links.py`** - walks `docs/**/*.html`, asserts every
  relative link resolves to a file inside the repository, and fails if any page
  fetches a script, stylesheet, font, image or frame off its own origin. It also
  covers the offer pages specifically: every product advertised on the index has
  a page, every product has exactly one buy button, every buy button is still the
  `#stripe-pending` placeholder with its fixed text and a known `data-product`,
  and no offer page carries an address or a personal name.
- **`govdiff paid-push`** - stages one feed's slice (a short faceless `README.md`,
  `data/<feed>/`, `diffs/<feed>/`, `.state/<feed>.json`, `docs/<feed>/feed.xml`
  and that feed's `changes.json`) and pushes it to every private repository
  configured for it, as `govdiff-bot`. Targets come from a single `PAID_TARGETS`
  secret holding a JSON array of `{feed, repo, deploy_key_b64}`; an absent or
  empty secret prints *"no paid targets configured - skipping"* and succeeds.
  `--dry-run` stages into a temp directory and prints the tree without touching
  any remote, `--report FILE` writes the machine-readable outcome the nightly
  reads, and `file://` remotes are supported so the whole path is tested against
  a local bare repository with no GitHub account and no network.
- **Per-feed `docs/<feed>/changes.json`**, written by `govdiff index` beside the
  Atom feeds: `format`, `feed`, `generated_at`, `head_start_hours`, `path_base`,
  `change_count`, a `latest` block and every change newest first, with paths
  relative to the repository root. It follows the same
  do-not-rewrite-what-has-not-moved rule as `docs/index.json`, so a quiet night
  leaves the file byte-identical and produces no commit.
- **A two-window nightly.** `.github/workflows/nightly.yml` now has two jobs.
  `harvest` at 06:15 UTC runs the tests, harvests each feed in its own
  `continue-on-error` step, rebuilds the index and change feed, pushes each
  feed's slice to its paid targets, and uploads the day's result as an Actions
  artifact `archive-<YYYY-MM-DD>` - one tarball per feed plus a manifest of
  every outcome. It never pushes to public `main`. `publish` at 18:15 UTC
  downloads that artifact, applies only the feeds whose morning harvest *and*
  paid push both succeeded, rebuilds the derived files from what it applied, and
  commits. There is no evening re-fetch, so the head start is exactly twelve
  hours and `.state/` never reaches the public archive early. A
  `workflow_dispatch` input `simulate_failure: <feed>` forces one feed to fail so
  the failure path can be exercised on a real run.
- **`HEAD_START_HOURS`** in `src/govdiff/config.py` - the only place the number
  12 is written. The harvest and publish crons are derived from it, every
  `changes.json` reports it, and `tests/test_schedule.py` parses the workflow
  YAML and fails if the gap between its two cron lines stops matching.
- **`launch/`** (excluded from the sdist) - `show-hn.md`, a faceless Show HN
  draft, and `checklist.md`, generated by the stdlib-only
  `launch/make_checklist.py` from the buy buttons actually present in
  `docs/offers/`, day 4's trusted-publishing table, the public flip and Pages
  enablement, and the 2026-09-22 date. `tests/test_launch.py` fails if the
  committed checklist and a fresh run disagree.

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

- **A quiet night no longer notifies a paid subscriber.** The slice copied the
  feed's `.state/<feed>.json` verbatim, and that file records `last_fetched_at`,
  `last_result` and `last_error` - the *run*, not the source - so every nightly
  push produced a commit in every paid repository even when no publisher had
  moved a byte. Proven on a real run: two harvests two minutes apart, nothing
  changed upstream, two commits and two notifications. `docs/paid.md` sells
  GitHub's own notification as the alert, so an alert every night would have
  been worth nothing. The staged copy now drops those three fields and keeps
  the ones that describe the source, exactly as `govdiff index` already does
  for `docs/index.json`. The public archive still commits the whole file - it
  is the conditional request's memory and `govdiff attest` reads the fetch time
  from it.
- **The held-back error names the right cause.** The publish job's final error
  said the paid push had failed, whichever of the two causes had actually held
  a feed back; a simulated harvest failure produced a run log that accused the
  paid push of a failure it had not had. It now points at the per-feed warning
  above it, which carries the real reason.

### Notes

- `__version__` is read from the installed package metadata, so `pyproject.toml`
  is the single source of truth and a source tree that was never installed says
  `0.0.0+source` rather than guessing.
- The sdist contains the tool only. `data/`, `diffs/`, `raw/`, `docs/`, `.state/`
  and `launch/` are pruned: they are the repository's product, not the package's,
  and `release.yml` fails the release if any of them leaks in.
- Paid targets are never named in a log. This repository becomes public on
  2026-09-22 and a public repository's Actions logs and artifacts are public with
  it, so `paid-push` and the nightly refer to each target as
  `target-<sha256[:8]>` of its URL and never print the URL itself.
- A paid target is a fresh shallow clone each night, not a force-pushed orphan
  branch. The subscriber's commit history is part of what is sold - it is the
  dated record and the thing GitHub's notifications are built on - and an orphan
  force-push would leave one commit and a "forced update" every night.
