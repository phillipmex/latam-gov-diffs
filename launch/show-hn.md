# Show HN draft

Paste the title and the body below into news.ycombinator.com/submit, unchanged.
Everything under "Notes for posting" is for the operator and is not part of the
post. `tests/test_launch.py` enforces the title length, the word count, and the
absence of a person.

## Title

Show HN: Nightly diffs of Brazilian and Mexican tax tables nobody archives

## Body

latam-gov-diffs is a nightly archive of three government tax tables from Brazil
and Mexico, with a machine-readable diff between every pair of consecutive
versions.

The case is sharpest for one of the three. SAT's Article 69-B list - the Mexican
register of taxpayers presumed to have issued invoices for operations that never
took place - is published as a replacement file. Every publication overwrites the
last. SAT keeps no history of it and nobody else does either, so once the file
has moved on there is no public way to answer "was this RFC on the definitive
list on 14 March?". Appearing on that list retroactively invalidates the invoices
a company issued, which makes it the difference between a deduction that
survives an audit and one that does not. The archive snapshots the list
every night and keeps the snapshot, so the question becomes answerable from that
night onward. It cannot answer it backwards: the history starts when the
harvester started, and that does not go away.

The other two are less dramatic and more useful day to day. Brazil's NF-e
cClassTrib table - the IBS/CBS classification codes for the 2026 tax reform - and
SAT's CFDI 4.0 catalogues both keep their own back-versions online, so those
diffs are reconstructed from files the publishers still host: nine changes and
one, respectively, as things stand. Nothing here scrapes a portal or needs a
login. It fetches the published document URLs, one conditional request per feed
per night, and stops on anything that looks like a challenge.

Free, and meant to stay that way: the archive, the diffs, an Atom feed, a
per-feed `changes.json` to poll, and a static viewer that deep-links to any
single change. Private copies of the same diffs, delivered twelve hours
earlier, are what pays for it.

One more honest limit: diffs are row-level and keyed on the publisher's own
identifier. A publisher that renumbers that column produces a diff reading as a
mass removal and re-add, and no automatic check can tell that apart from a real
one.

Repo: https://github.com/phillipmex/latam-gov-diffs
Viewer: https://phillipmex.github.io/latam-gov-diffs/

---

## Notes for posting

- Post **after** the repository is public, after the first Pages build has gone
  through, and after `v0.1.0` is on PyPI and npm. A Show HN whose links 404 is
  spent; there is no second one.
- Do not post the archive as "complete". The 69-B history is one snapshot deep
  on launch day and the post says so.
- The first comment will ask why the head start exists at all. The answer is in
  `docs/paid.md` and it is short: the free archive is complete and permanent, and
  the private copies are twelve hours, not twelve days, and not more data.
- If a publisher URL is dead on the day, say so in a comment rather than leaving
  a broken feed page up.
