/**
 * govdiff - a reader for the latam-gov-diffs archive.
 *
 * The archive is a public git repository, so this client is a thin thing: it
 * fetches one index file that says what exists, then fetches the diff files
 * that index points at. There is no API, no key and no server to be down.
 *
 * Everything hangs off one base URL. By default that is the raw file tree of
 * the published repository; set GOVDIFF_BASE_URL to point somewhere else (a
 * fork, a mirror, or the local http server the tests start). Every path in
 * index.json is relative to the repository root, so joining is just
 * concatenation.
 *
 * Zero dependencies, on purpose. Global fetch, Node 18 or newer.
 */

const DEFAULT_BASE_URL =
  "https://raw.githubusercontent.com/phillipmex/latam-gov-diffs/main/";

const INDEX_PATH = "docs/index.json";

// One index fetch per base URL per process. The archive changes once a night;
// a command that asks three questions should not ask three times.
const indexCache = new Map();

/** The base URL every path is resolved against, always with a trailing slash. */
export function baseUrl() {
  const configured = process.env.GOVDIFF_BASE_URL || DEFAULT_BASE_URL;
  return configured.endsWith("/") ? configured : configured + "/";
}

function resolve(path) {
  return baseUrl() + String(path).replace(/^\/+/, "");
}

async function getJson(path) {
  const url = resolve(path);
  const response = await fetch(url);
  if (!response.ok) {
    throw new Error(`GET ${url} failed: HTTP ${response.status}`);
  }
  return response.json();
}

/**
 * The whole archive index.
 * @param {{refresh?: boolean}} [options]
 */
export async function loadIndex(options = {}) {
  const key = baseUrl();
  if (!options.refresh && indexCache.has(key)) {
    return indexCache.get(key);
  }
  const index = await getJson(INDEX_PATH);
  indexCache.set(key, index);
  return index;
}

/** Forget any cached index. Mostly for tests and long-running processes. */
export function clearCache() {
  indexCache.clear();
}

/** Every feed in the archive, with its source metadata and its counts. */
export async function listFeeds() {
  const index = await loadIndex();
  return index.feeds.map((feed) => ({
    id: feed.id,
    title: feed.title,
    country: feed.country,
    publisher: feed.publisher,
    enabled: feed.enabled,
    documentUrl: feed.document_url,
    listingUrl: feed.listing_url,
    keyFields: feed.key_fields,
    versionCount: feed.version_count,
    diffCount: feed.diff_count,
    latestVersion: feed.latest_version,
  }));
}

async function feedEntry(feedId) {
  const index = await loadIndex();
  const found = index.feeds.find((feed) => feed.id === feedId);
  if (!found) {
    const known = index.feeds.map((feed) => feed.id).join(", ");
    throw new Error(`unknown feed '${feedId}' (known: ${known})`);
  }
  return found;
}

/** Stored versions of one feed, oldest first. */
export async function versions(feedId) {
  return (await feedEntry(feedId)).versions;
}

/** Diffs of one feed, in chain order. */
export async function diffs(feedId) {
  return (await feedEntry(feedId)).diffs;
}

/** The newest diff of a feed, or null when the feed has only one version. */
export async function latestDiff(feedId) {
  const all = await diffs(feedId);
  return all.length ? all[all.length - 1] : null;
}

async function diffEntry(feedId, from, to) {
  const all = await diffs(feedId);
  const found = all.find((entry) => entry.from === from && entry.to === to);
  if (!found) {
    throw new Error(
      `no diff ${from} -> ${to} for feed '${feedId}' ` +
        `(${all.length} diff(s) available)`,
    );
  }
  return found;
}

/** The `.summary.json` beside a diff: counts, schema drift, changed_fields. */
export async function summary(feedId, from, to) {
  return getJson((await diffEntry(feedId, from, to)).summary);
}

/**
 * The diff itself, one parsed record at a time.
 *
 * An async iterator rather than an array: a catCFDI revision is thousands of
 * records and megabytes of JSONL, and a caller that only wants the additions
 * should not have to hold the rest in memory. The response is streamed and
 * split on newlines as it arrives.
 *
 * @param {string} feedId
 * @param {string} from
 * @param {string} to
 * @returns {AsyncGenerator<object>}
 */
export async function* readDiff(feedId, from, to) {
  const entry = await diffEntry(feedId, from, to);
  const url = resolve(entry.jsonl);
  const response = await fetch(url);
  if (!response.ok) {
    throw new Error(`GET ${url} failed: HTTP ${response.status}`);
  }
  if (!response.body) {
    // Should not happen on Node 18+, but a body-less 200 must not look empty.
    throw new Error(`GET ${url} returned no body`);
  }

  const decoder = new TextDecoder("utf-8");
  let buffer = "";
  let lineNumber = 0;

  for await (const chunk of response.body) {
    buffer += decoder.decode(chunk, { stream: true });
    let newline = buffer.indexOf("\n");
    while (newline !== -1) {
      const line = buffer.slice(0, newline);
      buffer = buffer.slice(newline + 1);
      lineNumber += 1;
      const record = parseLine(line, lineNumber, url);
      if (record !== null) yield record;
      newline = buffer.indexOf("\n");
    }
  }
  buffer += decoder.decode();
  if (buffer.length) {
    lineNumber += 1;
    const record = parseLine(buffer, lineNumber, url);
    if (record !== null) yield record;
  }
}

function parseLine(line, lineNumber, url) {
  const text = line.trim();
  if (!text) return null;
  try {
    return JSON.parse(text);
  } catch (cause) {
    throw new Error(`${url}: line ${lineNumber} is not JSON`, { cause });
  }
}

export { DEFAULT_BASE_URL };
