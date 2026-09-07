#!/usr/bin/env node
/**
 * govdiff - command line reader for the latam-gov-diffs archive.
 *
 *   govdiff feeds
 *   govdiff versions <feed>
 *   govdiff latest <feed>
 *   govdiff diff <feed> <from> <to>
 */

import { createRequire } from "node:module";
import { pathToFileURL } from "node:url";

import {
  baseUrl,
  latestDiff,
  listFeeds,
  readDiff,
  summary,
  versions,
} from "./index.js";

// package.json is the single source of truth for the version, the same way
// pyproject.toml is on the Python side. npm always ships it in the tarball,
// `files` list or not, so this resolves for an installed package too.
const VERSION = createRequire(import.meta.url)("./package.json").version;

const USAGE = `govdiff ${VERSION} - read the latam-gov-diffs archive

  govdiff feeds                      every feed, with version and diff counts
  govdiff versions <feed>            stored versions, oldest first
  govdiff latest <feed>              the newest diff, summarised
  govdiff diff <feed> <from> <to>    the diff itself, one JSON record per line

Reads ${baseUrl()}
Set GOVDIFF_BASE_URL to read a fork, a mirror or a local checkout instead.`;

function pad(text, width) {
  const value = String(text ?? "");
  return value + " ".repeat(Math.max(0, width - value.length));
}

function table(headers, rows) {
  const widths = headers.map((header, column) =>
    Math.max(header.length, ...rows.map((row) => String(row[column] ?? "").length)),
  );
  const line = (cells) => cells.map((cell, i) => pad(cell, widths[i])).join("  ").trimEnd();
  const out = [line(headers), line(widths.map((w) => "-".repeat(w)))];
  for (const row of rows) out.push(line(row));
  return out.join("\n");
}

async function cmdFeeds() {
  const feeds = await listFeeds();
  console.log(
    table(
      ["feed", "country", "versions", "diffs", "latest", "title"],
      feeds.map((feed) => [
        feed.id,
        feed.country,
        feed.versionCount,
        feed.diffCount,
        feed.latestVersion ?? "-",
        feed.title,
      ]),
    ),
  );
}

async function cmdVersions(feedId) {
  const all = await versions(feedId);
  if (!all.length) {
    console.log(`${feedId}: no versions stored`);
    return;
  }
  console.log(
    table(
      ["version", "date", "rows", "columns", "sha256"],
      all.map((version) => [
        version.version_id,
        version.date,
        version.row_count,
        version.column_count,
        (version.sha256 ?? "").slice(0, 12),
      ]),
    ),
  );
}

async function cmdLatest(feedId) {
  const entry = await latestDiff(feedId);
  if (!entry) {
    const stored = (await versions(feedId)).length;
    console.log(
      `${feedId}: no diff yet (${stored} stored version${stored === 1 ? "" : "s"}; ` +
        "a diff needs two)",
    );
    return;
  }
  const detail = await summary(feedId, entry.from, entry.to);
  console.log(`${feedId}: ${entry.from} -> ${entry.to}`);
  console.log(
    `  ${detail.added} added, ${detail.changed} changed, ${detail.removed} removed, ` +
      `${detail.unchanged} unchanged (${detail.rows_from} -> ${detail.rows_to} rows)`,
  );
  if (detail.fields_added?.length) {
    console.log(`  columns added:   ${detail.fields_added.join(", ")}`);
  }
  if (detail.fields_removed?.length) {
    console.log(`  columns removed: ${detail.fields_removed.join(", ")}`);
  }
  const moved = Object.entries(detail.changed_fields ?? {}).sort((a, b) => b[1] - a[1]);
  if (moved.length) {
    console.log("  changed fields:");
    for (const [field, count] of moved) {
      console.log(`    ${pad(field, 40)} ${count}`);
    }
  }
}

async function cmdDiff(feedId, from, to) {
  for await (const record of readDiff(feedId, from, to)) {
    process.stdout.write(JSON.stringify(record) + "\n");
  }
}

export async function main(argv) {
  const [command, ...rest] = argv;

  if (!command || command === "--help" || command === "-h" || command === "help") {
    console.log(USAGE);
    return 0;
  }
  if (command === "--version" || command === "-V") {
    console.log(`govdiff ${VERSION}`);
    return 0;
  }

  try {
    switch (command) {
      case "feeds":
        await cmdFeeds();
        return 0;
      case "versions":
        if (rest.length !== 1) throw new Error("usage: govdiff versions <feed>");
        await cmdVersions(rest[0]);
        return 0;
      case "latest":
        if (rest.length !== 1) throw new Error("usage: govdiff latest <feed>");
        await cmdLatest(rest[0]);
        return 0;
      case "diff":
        if (rest.length !== 3) throw new Error("usage: govdiff diff <feed> <from> <to>");
        await cmdDiff(rest[0], rest[1], rest[2]);
        return 0;
      default:
        console.error(`unknown command '${command}'\n`);
        console.error(USAGE);
        return 2;
    }
  } catch (error) {
    console.error(`error: ${error.message}`);
    return 1;
  }
}

// `node cli.js` runs; `import "./cli.js"` from a test does not.
if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  process.exitCode = await main(process.argv.slice(2));
}
