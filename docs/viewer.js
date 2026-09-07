/*
 * The viewer. Vanilla JS, no build step, no dependency, no external request
 * beyond the archive files themselves.
 *
 * Three states, all driven by the address bar
 * -------------------------------------------
 *   (no hash)                          home - the feeds, and how to read them
 *   #feed=cclasstrib                   feed overview - source, and every change
 *   #feed=cclasstrib&from=…&to=…       one diff, record by record
 *
 * So every view is a link that can be bookmarked, pasted into a ticket, or
 * arrived at from the Atom feed, which is what `docs/feed.xml` links to.
 *
 * Where the archive lives
 * -----------------------
 * `index.json` always sits beside this page, so it is fetched as
 * `./index.json`. Everything it names - the `.jsonl` diffs, the
 * `.summary.json` files - is a path relative to the *repository root*, and
 * that root is somewhere different depending on where the page is running:
 *
 *   - On GitHub Pages the site root IS `docs/`, so `diffs/...` is simply not
 *     served. Those files are fetched from the repository's raw file tree
 *     instead (`raw_base_url` in index.json).
 *   - Served locally from the repository root (`python -m http.server`, page
 *     at `/docs/`), the archive is one directory up, so the base is `../`.
 *   - Either can be overridden with `#base=<url>` in the address bar, which is
 *     how you point the page at a fork or a mirror.
 *
 * Big diffs
 * ---------
 * A diff can be megabytes. The body is streamed and split line by line as it
 * arrives, and only the first RECORD_CAP records are kept for the table. The
 * rest are counted, not parsed, and the count is shown - so the page stays
 * responsive and still tells the truth about how much it is not showing.
 */

(function () {
  "use strict";

  var RECORD_CAP = 5000;
  var PAGE_SIZE = 200;
  var HIST_CAP = 25;

  var state = {
    index: null,
    base: null,
    view: null, // "home" | "overview" | "diff"
    feed: null,
    from: null,
    to: null,
    summary: null,
    records: [],
    total: 0,
    truncated: false,
    filtered: [],
    page: 0,
    histSort: "count", // or "name"
    token: 0, // guards against a slow load finishing after the user moved on
  };

  var el = {};

  /* ---------------------------------------------------------------- helpers */

  function $(id) {
    return document.getElementById(id);
  }

  function text(value) {
    return value === null || value === undefined ? "" : String(value);
  }

  function clear(node) {
    while (node.firstChild) node.removeChild(node.firstChild);
  }

  function make(tag, className, content) {
    var node = document.createElement(tag);
    if (className) node.className = className;
    if (content !== undefined) node.textContent = text(content);
    return node;
  }

  function link(href, className, content) {
    var node = make("a", className, content);
    node.href = href;
    return node;
  }

  function number(value) {
    return Number(value || 0).toLocaleString("en");
  }

  function bytes(value) {
    if (!value && value !== 0) return "";
    if (value < 1024) return value + " B";
    if (value < 1024 * 1024) return (value / 1024).toFixed(0) + " kB";
    return (value / (1024 * 1024)).toFixed(1) + " MB";
  }

  function endSlash(url) {
    return url.charAt(url.length - 1) === "/" ? url : url + "/";
  }

  function counts(diff) {
    return (
      "+" + number(diff.added) + " / ~" + number(diff.changed) + " / -" + number(diff.removed)
    );
  }

  /* ------------------------------------------------------------- hash state */

  function readHash() {
    var out = {};
    var raw = window.location.hash.replace(/^#/, "");
    if (!raw) return out;
    raw.split("&").forEach(function (part) {
      if (!part) return;
      var split = part.indexOf("=");
      var key = split === -1 ? part : part.slice(0, split);
      var value = split === -1 ? "" : part.slice(split + 1);
      out[decodeURIComponent(key)] = decodeURIComponent(value);
    });
    return out;
  }

  /* The one place a link is built, so `base` survives every navigation. */
  function hashFor(feed, from, to) {
    var parts = [];
    if (feed) parts.push("feed=" + encodeURIComponent(feed));
    if (from) parts.push("from=" + encodeURIComponent(from));
    if (to) parts.push("to=" + encodeURIComponent(to));
    var override = readHash().base;
    if (override) parts.push("base=" + encodeURIComponent(override));
    return "#" + parts.join("&");
  }

  function writeHash() {
    var hash =
      state.view === "home"
        ? hashFor(null, null, null)
        : hashFor(state.feed, state.from, state.to);
    // A bare "#" and an empty hash are the same address; only rewrite on a
    // real difference, so home does not churn the history entry.
    var current = window.location.hash || "#";
    if (current !== hash) history.replaceState(null, "", hash);
  }

  /* --------------------------------------------------------- base url logic */

  function detectBase(index) {
    var override = readHash().base;
    if (override) return endSlash(override);

    var host = window.location.hostname;
    var local = host === "localhost" || host === "127.0.0.1" || host === "[::1]" || host === "";
    if (local && window.location.protocol.indexOf("http") === 0) {
      // Served from the repository root; this page is at /docs/, so the
      // archive is one level up. Start the server at the repo root, not in
      // docs/, or the diff files are not reachable at all.
      return new URL("../", window.location.href).href;
    }
    // GitHub Pages (or anywhere else): docs/ is the whole site, so the diff
    // files have to come from the repository's raw tree.
    return endSlash(index.raw_base_url);
  }

  function url(path) {
    return state.base + String(path).replace(/^\/+/, "");
  }

  /* ------------------------------------------------------------ index lookup */

  function feedById(id) {
    for (var i = 0; i < state.index.feeds.length; i += 1) {
      if (state.index.feeds[i].id === id) return state.index.feeds[i];
    }
    return null;
  }

  function latestDiff(feed) {
    return feed && feed.diffs.length ? feed.diffs[feed.diffs.length - 1] : null;
  }

  function newestFirst(feed) {
    return feed.diffs.slice().reverse();
  }

  function currentDiff() {
    var feed = feedById(state.feed);
    if (!feed) return null;
    for (var i = 0; i < feed.diffs.length; i += 1) {
      if (feed.diffs[i].from === state.from && feed.diffs[i].to === state.to) return feed.diffs[i];
    }
    return null;
  }

  /* ----------------------------------------------------------------- routing */

  function show(view) {
    state.view = view;
    el.home.hidden = view !== "home";
    el.overview.hidden = view !== "overview";
    el.diff.hidden = view !== "diff";
  }

  function route() {
    var hash = readHash();
    var feed = hash.feed ? feedById(hash.feed) : null;
    if (!feed) {
      state.feed = null;
      state.from = null;
      state.to = null;
      renderHome();
      show("home");
      writeHash();
      return;
    }
    if (hash.from && hash.to) {
      var match = null;
      for (var i = 0; i < feed.diffs.length; i += 1) {
        if (feed.diffs[i].from === hash.from && feed.diffs[i].to === hash.to) {
          match = feed.diffs[i];
        }
      }
      if (!match) match = latestDiff(feed);
      if (match) {
        state.feed = feed.id;
        state.from = match.from;
        state.to = match.to;
        show("diff");
        enterDiff();
        return;
      }
    }
    state.feed = feed.id;
    state.from = null;
    state.to = null;
    renderOverview(feed);
    show("overview");
    writeHash();
  }

  function go(feed, from, to) {
    // Setting the hash is the navigation; the hashchange handler does the rest.
    var hash = hashFor(feed, from, to);
    if ((window.location.hash || "#") === hash) route();
    else window.location.hash = hash;
  }

  /* -------------------------------------------------------------- home view */

  function feedCard(feed) {
    var card = link(hashFor(feed.id, null, null), "feed-card");
    card.appendChild(make("h3", null, feed.id));
    card.appendChild(make("p", "who", feed.publisher + " (" + feed.country + ")"));
    card.appendChild(make("p", "what", feed.title));

    var stats = make("p", "stats");
    stats.appendChild(
      make(
        "span",
        null,
        number(feed.version_count) +
          " version" +
          (feed.version_count === 1 ? "" : "s") +
          " archived",
      ),
    );
    var newest = latestDiff(feed);
    if (newest) {
      stats.appendChild(make("span", null, counts(newest) + " on " + newest.to.slice(0, 10)));
    } else {
      stats.appendChild(make("span", null, "no change recorded yet"));
    }
    card.appendChild(stats);
    card.appendChild(make("span", "cta", "Open feed →"));
    return card;
  }

  function renderHome() {
    clear(el.feedCards);
    state.index.feeds.forEach(function (feed) {
      el.feedCards.appendChild(feedCard(feed));
    });
    el.rawExample.textContent = endSlash(state.index.raw_base_url) + "docs/index.json";
  }

  /* ---------------------------------------------------------- overview view */

  function metaRow(list, term, value) {
    list.appendChild(make("dt", null, term));
    var dd = make("dd");
    if (value && value.nodeType) dd.appendChild(value);
    else dd.textContent = text(value);
    list.appendChild(dd);
  }

  function renderOverview(feed) {
    el.overviewTitle.textContent = feed.id;
    el.overviewLede.textContent = feed.title;

    var meta = el.overviewMeta;
    clear(meta);
    metaRow(meta, "Publisher", feed.publisher);
    metaRow(meta, "Country", feed.country);
    if (feed.document_url) {
      var doc = link(feed.document_url, null, "the published file");
      doc.rel = "noreferrer";
      metaRow(meta, "Source document", doc);
    }
    if (feed.listing_url) {
      var listing = link(feed.listing_url, null, "the publisher's index page");
      listing.rel = "noreferrer";
      metaRow(meta, "Listing page", listing);
    }
    metaRow(meta, "Key fields", feed.key_fields.join(", ") || "(none)");
    metaRow(meta, "Format", feed.format);
    metaRow(meta, "Versions archived", number(feed.version_count));
    if (feed.versions.length) {
      metaRow(meta, "First version", feed.versions[0].date);
      metaRow(
        meta,
        "Latest version",
        feed.versions[feed.versions.length - 1].date +
          " (" +
          number(feed.versions[feed.versions.length - 1].row_count) +
          " rows)",
      );
    }
    metaRow(meta, "Changes recorded", number(feed.diff_count));

    el.overviewFeedLink.href = "./" + feed.id + "/feed.xml";
    el.overviewSubscribeNote.textContent =
      "Follow " +
      feed.id +
      " on its own, or every feed in the archive at once. Atom, so any reader can" +
      " take it; no account and nothing to install.";

    var list = el.timeline;
    clear(list);
    if (!feed.diffs.length) {
      el.timelineNote.textContent =
        "Nothing yet. A change needs two archived versions, and this feed has " +
        number(feed.version_count) +
        ". The first revision the publisher issues will appear here.";
      return;
    }
    el.timelineNote.textContent =
      number(feed.diff_count) + " change(s), newest first. Every row opens the records that moved.";
    newestFirst(feed).forEach(function (diff) {
      var item = make("li");
      var row = link(hashFor(feed.id, diff.from, diff.to), "timeline-row");
      row.appendChild(make("span", "when", diff.to.slice(0, 10)));
      var span = make("span", "span");
      span.appendChild(make("span", "from", diff.from.slice(0, 10)));
      span.appendChild(make("span", "arrow", " → "));
      span.appendChild(make("span", "to", diff.to.slice(0, 10)));
      row.appendChild(span);
      var tally = make("span", "tally");
      tally.appendChild(make("span", "n added", "+" + number(diff.added)));
      tally.appendChild(make("span", "n changed", "~" + number(diff.changed)));
      tally.appendChild(make("span", "n removed", "−" + number(diff.removed)));
      row.appendChild(tally);
      row.appendChild(make("span", "size", bytes(diff.jsonl_bytes)));
      item.appendChild(row);
      list.appendChild(item);
    });
  }

  /* -------------------------------------------------------------- diff view */

  function fillFeedPicker() {
    clear(el.feed);
    state.index.feeds.forEach(function (feed) {
      var option = make("option", null, feed.id + " - " + feed.title);
      option.value = feed.id;
      el.feed.appendChild(option);
    });
    el.feed.value = state.feed;
  }

  function fillPairPicker() {
    var feed = feedById(state.feed);
    clear(el.pair);
    if (!feed || !feed.diffs.length) {
      var none = make("option", null, "no change recorded yet");
      none.value = "";
      el.pair.appendChild(none);
      el.pair.disabled = true;
      return;
    }
    el.pair.disabled = false;
    // Newest first: that is the one a reader almost always wants.
    newestFirst(feed).forEach(function (diff) {
      var label =
        diff.from.slice(0, 10) + " to " + diff.to.slice(0, 10) + "  (" + counts(diff) + ")";
      var option = make("option", null, label);
      option.value = diff.from + "__" + diff.to;
      el.pair.appendChild(option);
    });
    el.pair.value = state.from + "__" + state.to;
  }

  function describeSource() {
    var feed = feedById(state.feed);
    clear(el.source);
    if (!feed) return;
    el.source.appendChild(
      document.createTextNode(
        feed.publisher + " (" + feed.country + "). Keyed by " + feed.key_fields.join(", ") + ". ",
      ),
    );
    if (feed.document_url) {
      var doc = link(feed.document_url, null, "source document");
      doc.rel = "noreferrer";
      el.source.appendChild(doc);
      el.source.appendChild(document.createTextNode(". "));
    }
    el.source.appendChild(
      document.createTextNode(
        number(feed.version_count) +
          " version(s) archived, " +
          number(feed.diff_count) +
          " change(s) recorded.",
      ),
    );
  }

  function updateCrumb() {
    el.crumbFeed.textContent = state.feed || "";
    el.crumbFeed.href = hashFor(state.feed, null, null);
  }

  function updateActions() {
    var diff = currentDiff();
    if (diff && diff.jsonl) {
      el.download.href = url(diff.jsonl);
      el.download.hidden = false;
      el.download.title = "The raw JSONL, " + bytes(diff.jsonl_bytes);
    } else {
      el.download.hidden = true;
      el.download.removeAttribute("href");
    }
    el.copy.textContent = "Copy link";
  }

  async function copyLink() {
    var href = window.location.href;
    try {
      if (navigator.clipboard && navigator.clipboard.writeText) {
        await navigator.clipboard.writeText(href);
      } else {
        // Older browsers, and any context where the async clipboard is not
        // available. A hidden textarea still works everywhere.
        var box = document.createElement("textarea");
        box.value = href;
        box.setAttribute("readonly", "readonly");
        box.style.position = "fixed";
        box.style.opacity = "0";
        document.body.appendChild(box);
        box.select();
        document.execCommand("copy");
        document.body.removeChild(box);
      }
      el.copy.textContent = "Link copied";
    } catch (error) {
      // Never a console error: say what to do instead.
      el.copy.textContent = "Copy failed - use the address bar";
    }
    window.setTimeout(function () {
      el.copy.textContent = "Copy link";
    }, 2500);
  }

  /* ------------------------------------------------------------- the summary */

  function card(kind, value, label) {
    var node = make("div", "card " + kind);
    node.appendChild(make("span", "n", number(value)));
    node.appendChild(make("span", "l", label));
    return node;
  }

  function histEntries(summary) {
    var entries = Object.keys(summary.changed_fields).map(function (name) {
      return [name, summary.changed_fields[name]];
    });
    if (state.histSort === "name") {
      entries.sort(function (a, b) {
        return a[0].localeCompare(b[0]);
      });
    } else {
      entries.sort(function (a, b) {
        return b[1] - a[1] || a[0].localeCompare(b[0]);
      });
    }
    return entries;
  }

  function sortButton(label, mode) {
    var button = make("button", state.histSort === mode ? "chip on" : "chip", label);
    button.type = "button";
    button.addEventListener("click", function () {
      if (state.histSort === mode) return;
      state.histSort = mode;
      renderSummary();
    });
    return button;
  }

  function renderChangedFields(summary) {
    var block = make("div");
    var head = make("div", "block-head");
    head.appendChild(make("h3", null, "Changed fields"));
    var sorter = make("div", "sorter");
    sorter.appendChild(make("span", "kf", "sort"));
    sorter.appendChild(sortButton("by count", "count"));
    sorter.appendChild(sortButton("by name", "name"));
    head.appendChild(sorter);
    block.appendChild(head);
    block.appendChild(
      make("p", "note", "Which columns moved, and on how many records."),
    );

    var entries = histEntries(summary);
    var top = Math.max.apply(
      null,
      entries.map(function (entry) {
        return entry[1];
      }),
    );
    var list = make("dl", "hist");
    entries.slice(0, HIST_CAP).forEach(function (entry) {
      list.appendChild(make("dt", null, entry[0]));
      var track = make("div", "bar-track");
      var fill = make("div", "bar-fill");
      fill.style.width = Math.max(2, Math.round((entry[1] / (top || 1)) * 100)) + "%";
      track.appendChild(fill);
      list.appendChild(track);
      list.appendChild(make("dd", null, number(entry[1])));
    });
    block.appendChild(list);
    if (entries.length > HIST_CAP) {
      block.appendChild(
        make("p", "note", "and " + number(entries.length - HIST_CAP) + " more columns"),
      );
    }
    return block;
  }

  function renderSummary() {
    clear(el.summary);
    var diff = currentDiff();
    if (!diff) {
      var feed = feedById(state.feed);
      var note = make("p", "note");
      note.textContent = feed
        ? "This feed has " +
          number(feed.version_count) +
          " archived version(s) and no change yet. A diff needs two versions; the first one" +
          " the publisher issues will appear here."
        : "";
      el.summary.appendChild(note);
      return;
    }

    var cards = make("div", "cards");
    cards.appendChild(card("added", diff.added, "added"));
    cards.appendChild(card("changed", diff.changed, "changed"));
    cards.appendChild(card("removed", diff.removed, "removed"));
    cards.appendChild(card("", diff.unchanged, "unchanged"));
    cards.appendChild(card("", diff.rows_to, "rows now (was " + number(diff.rows_from) + ")"));
    el.summary.appendChild(cards);

    var detail = make("div", "detail");
    var summary = state.summary;

    if (summary && summary.changed_fields && Object.keys(summary.changed_fields).length) {
      detail.appendChild(renderChangedFields(summary));
    }

    if (summary) {
      var drift = make("div");
      drift.appendChild(make("h3", null, "Columns the publisher added or dropped"));
      var added = summary.fields_added || [];
      var removed = summary.fields_removed || [];
      if (!added.length && !removed.length) {
        drift.appendChild(make("p", "note", "None - the shape of the table did not change."));
      } else {
        if (added.length) {
          drift.appendChild(make("p", "note", "Added:"));
          drift.appendChild(pills(added));
        }
        if (removed.length) {
          drift.appendChild(make("p", "note", "Dropped:"));
          drift.appendChild(pills(removed));
          drift.appendChild(
            make(
              "p",
              "note",
              "A dropped column makes every row that filled it read as changed. That is" +
                " correct, and it is why a revision can show thousands of changes and no new" +
                " information.",
            ),
          );
        }
      }
      detail.appendChild(drift);
    }

    if (detail.childNodes.length) el.summary.appendChild(detail);
  }

  function pills(values) {
    var list = make("ul", "pill-list");
    values.forEach(function (value) {
      list.appendChild(make("li", null, value));
    });
    return list;
  }

  /* -------------------------------------------------------- loading a diff */

  function setNote(message, isError) {
    clear(el.note);
    el.note.className = isError ? "note error" : "note";
    if (message) el.note.appendChild(message.nodeType ? message : document.createTextNode(message));
  }

  function enterDiff() {
    el.feed.value = state.feed;
    fillPairPicker();
    describeSource();
    updateCrumb();
    updateActions();
    writeHash();
    loadDiff();
  }

  async function loadDiff() {
    var token = (state.token += 1);
    state.records = [];
    state.total = 0;
    state.truncated = false;
    state.summary = null;
    state.page = 0;

    var diff = currentDiff();
    renderSummary();
    renderTable();

    if (!diff) {
      setNote("");
      return;
    }

    setNote("Loading " + diff.jsonl + " (" + bytes(diff.jsonl_bytes) + ")...");

    try {
      var summaryResponse = await fetch(url(diff.summary));
      if (summaryResponse.ok) {
        state.summary = await summaryResponse.json();
      }
    } catch (error) {
      state.summary = null; // the counts in index.json are enough to render
    }
    if (token !== state.token) return;
    renderSummary();

    try {
      await streamRecords(url(diff.jsonl), token);
    } catch (error) {
      if (token !== state.token) return;
      setNote(
        "Could not read " +
          url(diff.jsonl) +
          " - " +
          error.message +
          ". If you are running this page locally, start the server at the repository root" +
          " so that ../diffs/ is reachable, or set #base=<url> in the address bar.",
        true,
      );
      return;
    }
    if (token !== state.token) return;
    applyFilter();
  }

  async function streamRecords(target, token) {
    var response = await fetch(target);
    if (!response.ok) throw new Error("HTTP " + response.status);
    if (!response.body) {
      // No streaming available: fall back to reading it whole rather than
      // showing nothing.
      consume(await response.text(), true, token);
      return;
    }

    var reader = response.body.getReader();
    var decoder = new TextDecoder("utf-8");
    var buffer = "";
    for (;;) {
      var chunk = await reader.read();
      if (token !== state.token) {
        reader.cancel();
        return;
      }
      if (chunk.done) break;
      buffer += decoder.decode(chunk.value, { stream: true });
      var cut = buffer.lastIndexOf("\n");
      if (cut !== -1) {
        consume(buffer.slice(0, cut + 1), false, token);
        buffer = buffer.slice(cut + 1);
        renderProgress();
      }
    }
    buffer += decoder.decode();
    consume(buffer, true, token);
  }

  function consume(text, last, token) {
    if (token !== state.token) return;
    var lines = text.split("\n");
    for (var i = 0; i < lines.length; i += 1) {
      var line = lines[i];
      if (!line || !line.trim()) continue;
      state.total += 1;
      if (state.records.length < RECORD_CAP) {
        try {
          state.records.push(JSON.parse(line));
        } catch (error) {
          // A line that is not JSON is still a record that exists; count it
          // and carry on rather than abandoning the whole file.
          state.records.push({ op: "changed", key: { "unparsed line": String(state.total) } });
        }
      } else {
        // Past the cap the lines are counted, not parsed. That is the whole
        // trick that keeps a multi-megabyte diff from freezing the page.
        state.truncated = true;
      }
    }
    if (last) renderProgress();
  }

  function renderProgress() {
    var diff = currentDiff();
    if (!diff) return;
    var declared = diff.added + diff.changed + diff.removed;
    var message =
      number(state.total) + " of " + number(declared) + " records read from the diff file";
    if (state.truncated) {
      message +=
        ". Only the first " +
        number(RECORD_CAP) +
        " are shown in the table below; the rest are counted but not loaded, so the page stays" +
        " responsive. Use the filter on a smaller change, or download the JSONL.";
    }
    setNote(message);
  }

  /* ------------------------------------------------------------- the table */

  function recordText(record) {
    var parts = [record.op];
    var key = record.key || {};
    Object.keys(key).forEach(function (name) {
      parts.push(name, text(key[name]));
    });
    var body = record.fields || record.after || record.before || {};
    Object.keys(body).forEach(function (name) {
      parts.push(name);
      var value = body[name];
      if (value && typeof value === "object") {
        parts.push(text(value.before), text(value.after));
      } else {
        parts.push(text(value));
      }
    });
    return parts.join("  ").toLowerCase();
  }

  function applyFilter() {
    var needle = el.filter.value.trim().toLowerCase();
    var op = el.op.value;
    state.filtered = state.records.filter(function (record) {
      if (op !== "all" && record.op !== op) return false;
      if (!needle) return true;
      if (record._haystack === undefined) record._haystack = recordText(record);
      return record._haystack.indexOf(needle) !== -1;
    });
    state.page = 0;
    renderTable();
  }

  function keyCell(record) {
    var cell = make("td", "key");
    var key = record.key || {};
    Object.keys(key).forEach(function (name) {
      var part = make("div", "key-part");
      part.appendChild(make("span", "kf", name));
      // The record key is what a reader looks for first, so it is the largest
      // thing in the row rather than a label buried in a list of fields.
      part.appendChild(make("span", "kv", text(key[name]) || "(empty)"));
      cell.appendChild(part);
    });
    if (!cell.childNodes.length) cell.appendChild(make("span", "kf", "(no key)"));
    return cell;
  }

  function detailCell(record) {
    var cell = make("td");
    var list = make("dl", "fields");

    if (record.op === "changed") {
      var fields = record.fields || {};
      Object.keys(fields).forEach(function (name) {
        list.appendChild(make("dt", null, name));
        var dd = make("dd");
        dd.appendChild(make("span", "was", text(fields[name].before) || "(empty)"));
        dd.appendChild(make("span", "arrow", "→"));
        dd.appendChild(make("span", "now", text(fields[name].after) || "(empty)"));
        list.appendChild(dd);
      });
    } else {
      var body = record.op === "added" ? record.after || {} : record.before || {};
      var keys = Object.keys(record.key || {});
      Object.keys(body).forEach(function (name) {
        // The key columns are already in the Record column.
        if (keys.indexOf(name) !== -1) return;
        list.appendChild(make("dt", null, name));
        list.appendChild(make("dd", null, text(body[name])));
      });
    }

    if (!list.childNodes.length) {
      cell.appendChild(make("span", "kf", "(no other columns)"));
    } else {
      cell.appendChild(list);
    }
    return cell;
  }

  function renderTable() {
    var body = el.records.tBodies[0];
    clear(body);

    var pages = Math.max(1, Math.ceil(state.filtered.length / PAGE_SIZE));
    if (state.page >= pages) state.page = pages - 1;
    var start = state.page * PAGE_SIZE;
    var slice = state.filtered.slice(start, start + PAGE_SIZE);

    if (!slice.length) {
      var row = make("tr");
      var cell = make("td", null, state.records.length ? "Nothing matches that filter." : "");
      cell.colSpan = 3;
      row.appendChild(cell);
      body.appendChild(row);
    } else {
      slice.forEach(function (record) {
        var row = make("tr");
        var opCell = make("td");
        opCell.appendChild(make("span", "op op-" + record.op, record.op));
        row.appendChild(opCell);
        row.appendChild(keyCell(record));
        row.appendChild(detailCell(record));
        body.appendChild(row);
      });
    }

    el.prev.disabled = state.page === 0;
    el.next.disabled = state.page >= pages - 1;
    el.pageLabel.textContent = state.filtered.length
      ? "Records " +
        number(start + 1) +
        "-" +
        number(Math.min(start + PAGE_SIZE, state.filtered.length)) +
        " of " +
        number(state.filtered.length) +
        (state.filtered.length !== state.records.length
          ? " (filtered from " + number(state.records.length) + " loaded)"
          : "")
      : "No records";
  }

  /* ---------------------------------------------------------------- wiring */

  function renderProvenance() {
    var totals = state.index.feeds.reduce(
      function (acc, feed) {
        acc.versions += feed.version_count;
        acc.diffs += feed.diff_count;
        return acc;
      },
      { versions: 0, diffs: 0 },
    );
    el.provenance.textContent =
      "Index built " +
      state.index.generated_at +
      " - " +
      state.index.feeds.length +
      " feeds, " +
      number(totals.versions) +
      " archived versions, " +
      number(totals.diffs) +
      " recorded changes. Diff files are read from " +
      state.base;
  }

  async function start() {
    el.home = $("view-home");
    el.overview = $("view-overview");
    el.diff = $("view-diff");
    el.feedCards = $("feed-cards");
    el.rawExample = $("raw-example");
    el.overviewTitle = $("overview-title");
    el.overviewLede = $("overview-lede");
    el.overviewMeta = $("overview-meta");
    el.overviewFeedLink = $("overview-feed-link");
    el.overviewSubscribeNote = $("overview-subscribe-note");
    el.timeline = $("timeline");
    el.timelineNote = $("overview-timeline-note");
    el.crumbFeed = $("crumb-feed");
    el.feed = $("feed");
    el.pair = $("pair");
    el.copy = $("copy-link");
    el.download = $("download-jsonl");
    el.source = $("source");
    el.summary = $("summary");
    el.filter = $("filter");
    el.op = $("op");
    el.note = $("records-note");
    el.records = $("records");
    el.prev = $("prev");
    el.next = $("next");
    el.pageLabel = $("page-label");
    el.provenance = $("provenance");
    el.fatal = $("fatal");

    try {
      var response = await fetch("./index.json");
      if (!response.ok) throw new Error("HTTP " + response.status);
      state.index = await response.json();
    } catch (error) {
      el.fatal.hidden = false;
      el.fatal.textContent = "Could not read index.json next to this page - " + error.message;
      return;
    }

    state.base = detectBase(state.index);
    fillFeedPicker();
    renderProvenance();

    el.feed.addEventListener("change", function () {
      var feed = feedById(el.feed.value);
      var newest = latestDiff(feed);
      el.filter.value = "";
      el.op.value = "all";
      // A feed with nothing to diff yet has no diff view worth showing, so it
      // goes to its overview instead of an empty table.
      if (newest) go(feed.id, newest.from, newest.to);
      else go(feed.id, null, null);
    });

    el.pair.addEventListener("change", function () {
      var parts = el.pair.value.split("__");
      go(state.feed, parts[0], parts[1]);
    });

    el.copy.addEventListener("click", copyLink);
    el.filter.addEventListener("input", applyFilter);
    el.op.addEventListener("change", applyFilter);

    el.prev.addEventListener("click", function () {
      if (state.page > 0) {
        state.page -= 1;
        renderTable();
      }
    });
    el.next.addEventListener("click", function () {
      state.page += 1;
      renderTable();
    });

    window.addEventListener("hashchange", route);
    route();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", start);
  } else {
    start();
  }
})();
