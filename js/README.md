# govdiff (npm)

A zero-dependency Node client for the **latam-gov-diffs** archive: nightly
snapshots and record-level diffs of Latin American government reference data
(Brazil's cClassTrib table, Mexico's SAT CFDI 4.0 catalogues, and the SAT 69-B
list).

The archive is a public git repository, so this package is thin. It reads one
index file that says what exists, then reads the diff files that index points
at. No API key, no account, no server that can be down.

Full documentation, the diff format, and what each feed covers:
<https://github.com/phillipmex/latam-gov-diffs>.

## Install

```
npm install govdiff        # library
npx govdiff feeds          # command line, no install
```

Node 18 or newer. Available from launch, 2026-09-22.

## Command line

```
govdiff feeds                      every feed, with version and diff counts
govdiff versions <feed>            stored versions, oldest first
govdiff latest <feed>              the newest diff, summarised
govdiff diff <feed> <from> <to>    the diff itself, one JSON record per line
```

## Library

```js
import { listFeeds, versions, diffs, latestDiff, readDiff, summary } from "govdiff";

const feeds = await listFeeds();
const latest = await latestDiff("cclasstrib");
const counts = await summary("cclasstrib", latest.from, latest.to);

for await (const record of readDiff("cclasstrib", latest.from, latest.to)) {
  if (record.op === "added") console.log(record.key, record.after);
}
```

`readDiff` is an async iterator over the JSONL: records arrive as they are
streamed, so a caller can stop early without holding a multi-megabyte diff in
memory.

## Reading somewhere else

By default everything is fetched from
`https://raw.githubusercontent.com/phillipmex/latam-gov-diffs/main/`. Set
`GOVDIFF_BASE_URL` to read a fork, a mirror, or a local checkout served over
HTTP:

```
GOVDIFF_BASE_URL=http://127.0.0.1:8000/ govdiff feeds
```

MIT.
