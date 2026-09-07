# Paid feeds, attestations, and exactly how they are delivered

This is the whole commercial description of `latam-gov-diffs`. There is nothing
else: no sales call, no roster, no contract to negotiate. If something is not
written here, it is not part of what you are buying.

**Status: nothing is on sale before 2026-09-22.** Every buy button on this site
points at `#stripe-pending` and says so. The archive itself is free, public and
unmetered, and stays that way.

Sold and operated by **the latam-gov-diffs maintainers**. The only support
surface is GitHub issues.

---

## What you can buy

Prices are **US dollars**, monthly, and do not include any tax that may apply
where you are.

| product | what it covers | price |
|---|---|---|
| `cclasstrib` feed | Brazil, Portal Nacional da NF-e - the IBS/CBS tax classification table (cClassTrib) | **$28 / month** |
| `catalogos-sat` feed | Mexico, SAT - the 25 CFDI 4.0 catalogues of Anexo 20 | **$39 / month** |
| `listas-mx` feed | Mexico, SAT - the Article 69-B list (`Listado completo 69-B`) | **$99 / month** |
| `listas-mx` point-in-time attestation | one written statement about one RFC on one date, or across two dates | **$250 one-off** |

The three feeds are independent. Buying one does not include the others, and
there is no bundle.

The product names are the commercial names; inside the archive the same three
streams are the feed ids `cclasstrib`, `catcfdi` and `sat69b`.

---

## What a paid feed is

**An invite to a private GitHub repository carrying the same nightly diff
stream for that one output.** You get a repository, not an endpoint. Everything
below is what is in it and what happens to it.

### 1. The diffs land there first - a 12-hour head start

The harvester runs once a night at **06:15 UTC**. The diffs it produces are
committed to the private repository in that same run. The public archive's
commit for the same night is pushed **12 hours later, at 18:15 UTC**.

Twelve hours, and not some other number, because that is exactly one working
morning in both publishing countries. 06:15 UTC is 03:15 in Brasilia and 00:15
in Mexico City, so a subscriber's alert is waiting before their day starts;
18:15 UTC is 15:15 in Brasilia and 12:15 in Mexico City, so the free copy still
lands inside the same working day. A longer head start would only be an embargo
on a public archive whose whole job is to be public, and a shorter one would
land while everybody is asleep and be worth nothing.

**Be clear about what the head start is not.** It is a head start on *this
repository's* publication, not on the government's. SAT and the NF-e portal
publish to everyone at once; anyone watching those sources directly sees the
same file at the same moment you do. What you are twelve hours ahead of is the
free copy of the *diff*.

### 2. The alert is GitHub's own

Watch the private repository - **Watch → All Activity**, or **Custom →
Pushes** - and GitHub emails you, or notifies your phone through the GitHub
app, on every night that produced a change. A night that produced nothing
produces no commit and no notification. There is no separate mailing list to
subscribe to and no address to give anyone.

If you would rather not use notifications, the repository's Atom feed
(`https://github.com/<org>/<your-repo>/commits/main.atom`, which GitHub serves
for private repositories to people who can read them) works in any feed reader.

### 3. `changes.json`, for machines

Beside the diffs sits one file your code can poll instead of parsing commits:

```
changes.json
```

It is rewritten by the same nightly step that writes the diffs, and it is the
*only* file you need to read to know whether to do any work:

```json
{
  "format": 1,
  "feed": "cclasstrib",
  "generated_at": "2026-09-23T06:15:41+00:00",
  "head_start_hours": 12,
  "latest": {
    "from": "2026-04-15-cc0242ed",
    "to": "2026-06-23-1448cb63",
    "published": "2026-06-23",
    "added": 8, "changed": 156, "removed": 0,
    "rows_from": 156, "rows_to": 164,
    "fields_added": ["regulamento_cbs", "regulamento_ibs"],
    "fields_removed": [],
    "jsonl": "diffs/cclasstrib/2026-04-15-cc0242ed__2026-06-23-1448cb63.jsonl",
    "summary": "diffs/cclasstrib/2026-04-15-cc0242ed__2026-06-23-1448cb63.summary.json"
  },
  "changes": [ "... the same shape, newest first, for every change ever recorded ..." ]
}
```

Poll it, compare `latest.to` with the version id you last processed, and stop
if they match. `generated_at` moves only when the archive moved, so a
byte-identical file means there is nothing to do. The paths inside it are
relative to the repository root, exactly as in the public
[`docs/index.json`](./index.json), so the same reader code works against either.

### 4. Support is a GitHub issue, answered within 2 business days

Open an issue in your private repository. **First response within two business
days** (Monday to Friday, public holidays in Mexico or Brazil excluded), on
questions about the feed, the format, a record you cannot make sense of, or a
harvest that looks wrong.

Two business days is a response, not a fix. A parser that broke because a
publisher restructured a file gets fixed as fast as it can be fixed, and the
issue says where it stands until it is.

---

## What is *not* included

Written plainly, because the things people assume are included are the
expensive ones:

- **No hosted API.** There is no endpoint, no base URL to call, no API key, no
  rate limit and no query language. You clone a git repository or read raw files
  from it.
- **No webhooks.** Nothing calls your server. GitHub notifications and
  `changes.json` are the two ways you find out.
- **No SLA.** Best effort, nightly. The workflow runs on GitHub's free hosted
  runners; if GitHub is down, or a publisher is down, or a publisher changes a
  file so much the parser stops recognising it, that night produces nothing.
  There is no credit, no uptime figure and no penalty clause, because there is
  no infrastructure here to promise anything about.
- **No exclusivity, and no delay of the public archive beyond the 12 hours
  above.** The free tier keeps everything.
- **No custom feeds, no custom columns, no per-customer parsing** at these
  prices.
- **No legal opinion of any kind.** See the attestation section.
- **No phone, no video call, no email address.** GitHub issues, and nothing
  else.

---

## The $250 point-in-time attestation

**One written statement about one RFC.** It answers the question SAT's own site
cannot: *what did the Article 69-B list say on a particular day?*

### What you get

A document, delivered as Markdown and laid out so it prints straight to PDF
from any browser or editor, that states:

- whether the RFC appeared on the SAT 69-B list **on a given date**, or across
  **two dates** if you ask for a span;
- the `situacion del contribuyente` it carried (`Presunto`, `Desvirtuado`,
  `Definitivo` or `Sentencia Favorable`), and if it changed inside the span,
  where it changed;
- every oficio number and publication date the list recorded for that
  proceeding, SAT-side and DOF-side, exactly as SAT wrote them;
- the **snapshot version ids** the answer is drawn from, **their sha256** - the
  hash of the bytes SAT actually served - the **SAT document URL**, and the
  **`Last-Modified` value SAT reported at the time**;
- the observation timestamps on both sides of the answer, so the edge of the
  evidence is visible rather than implied.

An RFC that appears in two unrelated proceedings gets both records; the
document never silently picks one.

**Delivery:** into your private repository if you already have a `listas-mx`
subscription, or as a GitHub gist link if you do not. **Turnaround: 3 business
days** from payment and from your telling us the RFC and the date.

### The honest limit, which is also the whole point

**Coverage begins 2026-09-07** - the day this archive took its first snapshot
of the list - and **cannot reach any earlier date**.

That is not a gap that will be filled later. SAT publishes the 69-B list as a
single file that is overwritten in place: no dated filenames, no versioned URL,
no public history. Nobody can tell you what the list said on 2025-04-12,
including us, including SAT's own website. The only way anyone will ever be
able to answer that question about 2027 is that somebody was taking a copy every
night through 2027 - which is exactly why this archive exists and why every day
of it is worth more than the day before.

If the date you need is before 2026-09-07, say so and do not buy this. You will
be told the same thing in writing and refunded.

### Not legal advice

The attestation reports what an archived copy of a public SAT file said on a
given date. It is **not legal advice**, it is **not a substitute for SAT's own
constancia** or for a query against SAT's live service, and it states nothing
about the validity of any invoice, deduction or contract. It is evidence of what
was published, and nothing more.

### You can also produce it yourself, free

The archive is public and the tool is open source. The same document comes out
of:

```
govdiff attest sat69b --rfc AAA010101AAA --on 2026-09-22
govdiff attest sat69b --rfc AAA010101AAA --between 2026-09-22 2026-10-31
```

run inside a clone of the public repository. It reads the stored snapshots and
makes no network request. What the $250 buys is that somebody else runs it,
signs the result, and keeps the archive it reads from running - not access to a
secret.

---

## Fulfilment - the operator's steps

One checkout, five steps, no automation. Done by hand, same day where possible.

1. **Create the private repository.** `latam-gov-diffs-<product>-<short buyer
   ref>` under the same GitHub account, private, no description, no topics.
   Seed it with the archive's existing history for that one feed
   (`data/<feed>/`, `diffs/<feed>/`, `.state/<feed>.json`), the feed's
   `README.md`, and `changes.json`.
2. **Add the feed to the nightly job's private targets** so that night's harvest
   commits there at 06:15 UTC.
3. **Send the invite.** GitHub → repository → Settings → Collaborators → add the
   username or email the buyer gave at checkout, **Read** permission. GitHub
   sends the invitation itself; no message from us is needed and none is sent.
4. **Record the order** in the private ledger: product, date, buyer's GitHub
   handle, repository name, Stripe reference. Nothing else about the buyer is
   kept.
5. **On cancellation - the invite is revoked.** Stripe reports the cancellation;
   at the end of the paid period the collaborator is removed and the private
   repository is archived. Anything already cloned stays cloned; nothing is
   clawed back, and there is nothing to uninstall. The public archive is still
   there, free, twelve hours behind.

**Refunds:** full refund on request within 14 days of a first payment or of an
attestation order; after that, cancel any time and access runs to the end of the
period already paid for.

---

## Checkout, and the placeholder that stands in for it

Stripe payment links do not exist yet. They are created by the owner around
**2026-09-19** and go live at launch on **2026-09-22**.

Until then, every buy button on every offer page follows one convention, so that
turning them on is a find-and-replace and nothing else:

```html
<a class="button buy" href="#stripe-pending" data-product="cclasstrib-monthly">
  Checkout opens on launch (2026-09-22)
</a>
```

- the `href` is exactly `#stripe-pending` - a fragment, so it is never a dead
  external link and never a 404;
- the visible text is exactly *Checkout opens on launch (2026-09-22)*;
- `data-product` names which of the four products the button is for;
- an HTML comment beside every button names the attribute the real link is
  pasted into.

**On launch day:** replace the `href` value with the Stripe payment link for
that `data-product`, and replace the visible text with the price. Four buttons,
four links, one pass over `docs/offers/`.

---

## Where the free tier ends

Everything the free tier has stays free and unmetered: the whole archive, every
diff ever recorded, the [viewer](./index.html), the [Atom change feed](./feed.xml),
`docs/index.json`, `CHANGES.md`, and both open-source clients. No account, no
key, no sign-up, and no counting.

The paid tier is three things and only three: **twelve hours earlier**,
**an alert that comes to you**, and **somebody to ask**. If none of those three
is worth $28 a month to you, the free tier is genuinely the right answer and
you should use it.
