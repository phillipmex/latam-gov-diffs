/**
 * Tests run against the real archive in this repository, served over HTTP by a
 * throwaway server started here.
 *
 * Not `file://`: global fetch refuses that scheme outright, which is the whole
 * reason this file starts a server instead of pointing GOVDIFF_BASE_URL at a
 * path. The server's root is the repository root, so `docs/index.json` and the
 * `diffs/...` paths inside it resolve exactly as they will against
 * raw.githubusercontent.com.
 */

import assert from "node:assert/strict";
import { createReadStream, existsSync, statSync } from "node:fs";
import { createServer } from "node:http";
import { after, before, describe, it } from "node:test";
import { dirname, join, normalize, resolve, sep } from "node:path";
import { fileURLToPath } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const REPO_ROOT = resolve(HERE, "..", "..");

const CONTENT_TYPES = {
  ".json": "application/json; charset=utf-8",
  ".jsonl": "application/x-ndjson; charset=utf-8",
};

let server;
let client;

function startServer() {
  return new Promise((ready) => {
    server = createServer((request, response) => {
      const path = decodeURIComponent(new URL(request.url, "http://127.0.0.1").pathname);
      const target = normalize(join(REPO_ROOT, path));
      // Refuse anything that climbs out of the repository.
      if (!target.startsWith(REPO_ROOT + sep)) {
        response.writeHead(403).end("no");
        return;
      }
      if (!existsSync(target) || !statSync(target).isFile()) {
        response.writeHead(404).end("not found");
        return;
      }
      const dot = target.lastIndexOf(".");
      response.writeHead(200, {
        "content-type": CONTENT_TYPES[target.slice(dot)] || "application/octet-stream",
        "content-length": statSync(target).size,
      });
      createReadStream(target).pipe(response);
    });
    server.listen(0, "127.0.0.1", () => ready(server.address().port));
  });
}

before(async () => {
  const port = await startServer();
  process.env.GOVDIFF_BASE_URL = `http://127.0.0.1:${port}`; // no trailing slash on purpose
  client = await import("../index.js");
  client.clearCache();
});

after(() => {
  server?.close();
});

describe("base URL", () => {
  it("adds the trailing slash the caller left off", () => {
    assert.ok(client.baseUrl().endsWith("/"));
  });

  it("defaults to the published archive", () => {
    assert.equal(
      client.DEFAULT_BASE_URL,
      "https://raw.githubusercontent.com/phillipmex/latam-gov-diffs/main/",
    );
  });
});

describe("listFeeds", () => {
  it("returns every feed in the archive", async () => {
    const feeds = await client.listFeeds();
    const ids = feeds.map((feed) => feed.id).sort();
    assert.deepEqual(ids, ["catcfdi", "cclasstrib", "sat69b"]);
  });

  it("carries the source metadata, not just the id", async () => {
    const feeds = await client.listFeeds();
    const cclasstrib = feeds.find((feed) => feed.id === "cclasstrib");
    assert.equal(cclasstrib.country, "BR");
    assert.match(cclasstrib.publisher, /Nota Fiscal Eletronica/);
    assert.deepEqual(cclasstrib.keyFields, ["cclasstrib"]);
    assert.ok(cclasstrib.documentUrl.startsWith("https://"));
    assert.ok(cclasstrib.versionCount >= 10);
  });
});

describe("versions", () => {
  it("lists the stored versions oldest first", async () => {
    const all = await client.versions("cclasstrib");
    assert.ok(all.length >= 10);
    const ids = all.map((version) => version.version_id);
    assert.deepEqual(ids, [...ids].sort());
    assert.equal(ids[0], "2024-12-07-67a71e9a");
  });

  it("gives each version a date, a row count and a hash", async () => {
    const [first] = await client.versions("cclasstrib");
    assert.equal(first.date, "2024-12-07");
    assert.equal(first.row_count, 94);
    assert.match(first.sha256, /^[0-9a-f]{64}$/);
    assert.equal(first.parquet, "data/cclasstrib/2024-12-07-67a71e9a/data.parquet");
  });

  it("refuses an unknown feed and says which feeds exist", async () => {
    await assert.rejects(() => client.versions("nope"), /unknown feed 'nope'.*cclasstrib/s);
  });
});

describe("diffs and latestDiff", () => {
  it("returns the diffs in chain order", async () => {
    const all = await client.diffs("cclasstrib");
    assert.ok(all.length >= 9);
    for (let i = 1; i < all.length; i += 1) {
      assert.equal(all[i].from, all[i - 1].to, "each diff starts where the last one ended");
    }
  });

  it("latestDiff is the last link in the chain", async () => {
    const all = await client.diffs("cclasstrib");
    const latest = await client.latestDiff("cclasstrib");
    assert.deepEqual(latest, all[all.length - 1]);
  });

  it("latestDiff is null for a feed with one version and no diff", async () => {
    assert.equal(await client.latestDiff("sat69b"), null);
  });
});

describe("summary", () => {
  it("reads the .summary.json beside the diff", async () => {
    const detail = await client.summary(
      "cclasstrib",
      "2025-10-03-b5ed31f4",
      "2025-11-24-431d4217",
    );
    assert.equal(detail.format, 2);
    assert.equal(detail.added, 7);
    assert.equal(detail.changed, 25);
    assert.equal(detail.removed, 4);
    assert.deepEqual(detail.fields_removed, ["credito_para"]);
    assert.equal(detail.changed_fields.link, 11);
  });

  it("refuses a version pair that is not a stored diff", async () => {
    await assert.rejects(
      () => client.summary("cclasstrib", "2024-12-07-67a71e9a", "2026-06-23-1448cb63"),
      /no diff .* -> /,
    );
  });
});

describe("readDiff", () => {
  it("yields one parsed record per line, and as many as the summary counts", async () => {
    const from = "2025-10-03-b5ed31f4";
    const to = "2025-11-24-431d4217";
    const detail = await client.summary("cclasstrib", from, to);
    const expected = detail.added + detail.changed + detail.removed;

    const ops = { added: 0, changed: 0, removed: 0 };
    for await (const record of client.readDiff("cclasstrib", from, to)) {
      assert.ok(record.key, "every record carries its key");
      ops[record.op] += 1;
    }
    assert.equal(ops.added, detail.added);
    assert.equal(ops.changed, detail.changed);
    assert.equal(ops.removed, detail.removed);
    assert.equal(ops.added + ops.changed + ops.removed, expected);
  });

  it("is an iterator, so a caller can stop early without reading the rest", async () => {
    const seen = [];
    for await (const record of client.readDiff(
      "catcfdi",
      "2024-12-04-a4b88178",
      "2026-09-03-a5ce7a60",
    )) {
      seen.push(record);
      if (seen.length === 5) break;
    }
    assert.equal(seen.length, 5);
    assert.ok(["added", "changed", "removed"].includes(seen[0].op));
  });

  it("splits records correctly across chunk boundaries", async () => {
    // The catCFDI diff is megabytes, so it arrives in many chunks; every line
    // must still parse. Reading the first 2,000 records exercises the buffer.
    let count = 0;
    for await (const record of client.readDiff(
      "catcfdi",
      "2024-12-04-a4b88178",
      "2026-09-03-a5ce7a60",
    )) {
      assert.equal(typeof record.op, "string");
      count += 1;
      if (count === 2000) break;
    }
    assert.equal(count, 2000);
  });

  it("format 2 records carry only what moved", async () => {
    for await (const record of client.readDiff(
      "cclasstrib",
      "2025-10-03-b5ed31f4",
      "2025-11-24-431d4217",
    )) {
      if (record.op === "changed") {
        assert.ok(record.fields, "a change lists its moved columns");
        assert.equal(record.before, undefined);
        const [first] = Object.values(record.fields);
        assert.ok("before" in first && "after" in first);
        break;
      }
    }
  });
});

describe("the CLI", () => {
  it("prints the feed table", async () => {
    const { main } = await import("../cli.js");
    const lines = [];
    const real = console.log;
    console.log = (text) => lines.push(text);
    try {
      assert.equal(await main(["feeds"]), 0);
    } finally {
      console.log = real;
    }
    const out = lines.join("\n");
    assert.match(out, /cclasstrib/);
    assert.match(out, /catcfdi/);
    assert.match(out, /sat69b/);
  });

  it("summarises the latest diff", async () => {
    const { main } = await import("../cli.js");
    const lines = [];
    const real = console.log;
    console.log = (text) => lines.push(text);
    try {
      assert.equal(await main(["latest", "cclasstrib"]), 0);
    } finally {
      console.log = real;
    }
    const out = lines.join("\n");
    assert.match(out, /added, .*changed, .*removed/);
  });

  it("reports an unknown feed as an error, not a crash", async () => {
    const { main } = await import("../cli.js");
    const errors = [];
    const real = console.error;
    console.error = (text) => errors.push(text);
    try {
      assert.equal(await main(["versions", "nope"]), 1);
    } finally {
      console.error = real;
    }
    assert.match(errors.join("\n"), /unknown feed 'nope'/);
  });

  it("rejects an unknown command", async () => {
    const { main } = await import("../cli.js");
    const real = console.error;
    console.error = () => {};
    try {
      assert.equal(await main(["wat"]), 2);
    } finally {
      console.error = real;
    }
  });
});
