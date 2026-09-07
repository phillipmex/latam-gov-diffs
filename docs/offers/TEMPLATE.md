# The offer-page template

Every page in `docs/offers/` is one hand-written HTML file with the same
skeleton. There is no build step, no templating engine and no shared partial:
you copy the nearest finished page, change the words, and check it against this
document. `cclasstrib.html` is the reference implementation - when the two
disagree, the HTML is right and this file is out of date.

Read [`../paid.md`](../paid.md) first. It is the source of truth for prices,
delivery mechanics, refunds and the checkout placeholder; an offer page only
restates what is written there. Nothing may appear on an offer page that
`paid.md` does not back up.

---

## Hard rules

1. **Zero external requests.** No web font, no CDN, no image host, no
   analytics. `tests/test_docs_links.py` fails the build if a page fetches
   anything off its own origin, and it also fails if any relative link points
   at a file that does not exist.
2. **The page must read correctly with JavaScript off.** Every number is
   written into the HTML by hand. The one inline script *replaces* those
   numbers with fresher ones from `../index.json`; it never introduces content
   that was not already there.
3. **One inline `<script>` per page, at the end of `<body>`,** doing exactly two
   jobs: the index fetch and the copy-link button. No external script file.
4. **Truth only.** Every figure on the page must be checkable against
   `docs/index.json` or a `diffs/<feed>/*.summary.json` file in this
   repository. Verify before writing, not after.
5. **No testimonials, no logos, no urgency, no names.** No "only 3 seats left",
   no countdown, no customer quotes, no personal name or email anywhere. The
   seller is *the latam-gov-diffs maintainers*.
6. **No Stripe link.** The buy button uses the placeholder in section 4 below,
   and nothing else, until the owner turns it on at launch.

---

## The skeleton

```
<head>
  <title> …                      "<product> - latam-gov-diffs"
  <meta name="description">
  <link rel="stylesheet" href="../viewer.css">   ← tokens, body, .button, .links
  <link rel="stylesheet" href="./offer.css">     ← everything offer-specific
  <link rel="icon" href="data:image/svg+xml,…">  ← copied verbatim from ../index.html

<body>
  <header>
    <div class="bar"> <h1><a href="../index.html">latam-gov-diffs</a></h1>
      <nav> Viewer · Change feed · Paid feeds · Repository </nav>
    <p class="tagline">                          one line, what the site is

  <main class="offer">
    1. <h2> the product name and the feed it comes from
    2. <p class="promise">     one sentence, one idea, no clause about price
    3. <aside class="translated"> …               the publisher's own language
    4. <section id="what-you-get">   <ul class="gets"> … <ul class="gets nots">
    5. <section id="what-it-costs">  <div class="price-box"> price + buy button
    6. <section id="proof">          <div class="proof"> stats, then examples
    7. <section id="delivery">       <ol class="steps">, link to ../paid.md
    8. <section id="faq">            <div class="faq"> 5-7 <details>
  </main>

  <footer class="offer-footer">  viewer · feed.xml · GitHub · free tier
  <script> …                     index fetch + copy link, in that order
```

---

## 1-2. Title and promise

`<h1>` is the site, not the product - the product name is the first `<h2>`, so
the page has one heading level per level of meaning and the header bar is
identical on every page.

`class="promise"` is one sentence and one idea. It says what the reader gets to
know, not what they pay or how it is delivered:

> Know what changed in Brazil's IBS/CBS classification table before your next
> release ships.

Do not put the price in the promise. Do not put two sentences in it.

## 3. The publisher's own language

One paragraph, in the language of the country the data comes from - pt-BR for a
Brazilian source, es-MX for a Mexican one - directly under the promise, marked
up as:

```html
<aside class="translated" lang="pt-BR">
  <span class="lang">Em português</span>
  <p>…</p>
</aside>
```

Keep it short and plain: what the feed is, what it costs, where the free
version is. Machine-translation quality is acceptable; length is not. The
`lang` attribute is required, or a screen reader reads Portuguese with an
English voice.

## 4. What you get, and what you do not

Two lists, in this order, both `class="gets"`; the second also carries `nots`,
which swaps the tick for a minus:

```html
<ul class="gets">
  <li><b>The diffs twelve hours early.</b> …</li>
</ul>

<h3>What is not included</h3>
<ul class="gets nots">
  <li><b>No hosted API.</b> …</li>
</ul>
```

The "not" list is not optional and is not a footnote. It is the shortest way to
stop a buyer expecting an API, and it is the reason the page can be believed.
Keep it to the four or five things a reader would otherwise assume.

## 5. What it costs

```html
<div class="price-box">
  <p class="price"><span class="amount">$28</span> <span class="per">per month, USD</span></p>
  <p>…one line on what the money buys and what cancelling does…</p>

  <!-- LAUNCH: paste the Stripe payment link into the href below, and replace
       the visible text with the price. Nothing else on this page changes. -->
  <a class="buy" href="#stripe-pending" data-product="cclasstrib-monthly">
    Checkout opens on launch (2026-09-22)
  </a>
  <p class="buy-note">…refund line, and a pointer to ../paid.md…</p>
</div>
```

The `href` is exactly `#stripe-pending`, the visible text is exactly *Checkout
opens on launch (2026-09-22)*, and the HTML comment naming the attribute sits
directly above the button. `data-product` is the product id used in `paid.md`.

## 6. Proof from the archive

Four `.stat` boxes, each with a `.n` (the number) and a `.l` (what it counts).
Every `.n` carries an `id`, and the same value is written in the HTML as the
static fallback:

```html
<div class="proof">
  <div class="stat"><span class="n" id="stat-versions">10</span><span class="l">dated releases archived</span></div>
  …
</div>
<p class="proof-source" id="proof-source">
  Counted from the archive index on 2026-09-07. …
</p>
```

Then `<ul class="changes">` - two to four *real* changes, each with the dates
it happened between and what it would have broken. Quote field names as they
appear in the diff summaries; do not paraphrase them.

The script at the bottom of the page reads `../index.json`, finds the feed by
id, and overwrites the four `.n` values and `#proof-source`. If the fetch fails
- offline, `file://`, JavaScript off - the baked-in numbers stand and the
sentence still says where they came from. Both states must be correct, so
re-bake the fallback whenever the numbers move.

## 7. How delivery works

An `<ol class="steps">` of what happens after payment - four or five steps,
ending with cancellation - and a link to
[`../paid.md`](../paid.md) for the full version. The offer page summarises;
`paid.md` is normative.

## 8. FAQ

Five to seven `<details>` inside `<div class="faq">`. At least three of them
must be the questions a sceptical buyer would ask and a seller would rather
avoid. The mandatory three:

- **Can I get this history somewhere else / is it backfillable?** Answer
  honestly per feed. For `cclasstrib` the answer is *yes, the NF-e portal keeps
  the back versions online* - what is sold is the diff, not the archive. For
  `sat69b` the answer is *no, and that is the whole point*.
- **What happens if the publisher changes the file format?** The harvest for
  that night produces nothing, the issue tracker says so, and the parser is
  fixed as fast as it can be.
- **What happens when I cancel?** The invite is revoked at the end of the paid
  period; anything already cloned stays cloned; the free archive is still
  there.

The first `<details>` on the page may carry `open` so the section does not read
as empty. Never put an answer only in the summary line.

## Footer

```html
<footer class="offer-footer">
  <p class="links">
    <a href="../index.html">Viewer</a>
    <a href="../feed.xml">Change feed</a>
    <a href="https://github.com/phillipmex/latam-gov-diffs">GitHub</a>
    <a href="../index.html#feed=<id>">The free tier for this feed</a>
    <button class="copy" type="button" hidden>Copy link</button>
  </p>
  <p>Published by the latam-gov-diffs maintainers. …</p>
</footer>
```

The copy button ships with `hidden` and the script removes it only when
`navigator.clipboard` exists, so nobody is offered a control that cannot work.

---

## Before committing a new page

```
python -m pytest -q tests/test_docs_links.py
```

then serve the repository root and open the page in a clean headless Chrome:

```
python -m http.server 8000
```

Check, in this order: no console errors; the page in light and in dark; no
horizontal scrollbar at 390 px wide; the proof numbers change when the fetch
succeeds and are still right when it is blocked; every link in the footer
resolves.
