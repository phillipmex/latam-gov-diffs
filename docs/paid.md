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

The harvester runs **once a night, at 06:15 UTC**, and that single run is the
only moment in the day when anything is fetched from a government publisher.
What it produces is committed to the private repositories in that same run, and
to nothing else - the public archive is not touched at 06:15.

Twelve hours later, at **18:15 UTC**, a second job publishes that *same*
result to the public archive. It re-fetches nothing. It takes the morning run's
own output, applies it, rebuilds the index and the change feed from what it
applied, and commits.

There is deliberately no evening re-fetch, and that is what turns the head start
from an average into a number:

* **It cannot invert.** If the evening job went back to the publishers, a file
  that first appeared at, say, 14:00 UTC would reach the free archive that same
  night and the private repositories the next morning - the free tier first, by
  ten hours. There is no evening fetch, so that cannot happen.
* **It is exactly twelve hours, every night.** Not "up to twelve", not "about
  twelve". The two jobs run from the same constant in the source, and a test
  fails the build if the schedule and the constant ever stop agreeing.
* **Nothing leaks early.** `.state/<feed>.json` - the conditional-request memory
  recording which version was last seen - is a committed file, and a reader who
  watched it would learn that something had changed before the diff was public.
  The morning job pushes nothing public at all, so it cannot.
* **A feed whose delivery failed is not published.** If the 06:15 push to a paid
  repository fails, the 18:15 job holds that feed back from the public archive,
  says exactly why in the run log, and ends by failing so the operator gets
  GitHub's failed-run email. That feed goes public the following evening, after
  a morning run that actually delivered it. What is never allowed to happen is
  the free copy going out for a night the paid copy did not.

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

That promise is a property of what is copied into your repository, not a
hope. Your copy of `.state/<feed>.json` carries the fields that describe the
*source* - version id, sha256, `Last-Modified`, row count - and omits the
three that describe our nightly *run*, including the timestamp of the last
fetch. Those move every night whether or not the publisher moved a byte, and
carrying them would have committed to your repository, and emailed you, on
every quiet night. Two nights that fetched identical bytes now stage
byte-identical files, and git finds nothing to commit.

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
Two more fields sit beside those shown: `change_count`, the length of `changes`,
and `path_base`, which is the string `repository-root` and exists so a future
change of convention is detectable rather than silent. On a feed that has never
recorded a change, `latest` is `null` and `changes` is `[]`.

The same file is written for the free archive at `docs/<feed>/changes.json` -
[cclasstrib](./cclasstrib/changes.json), [catcfdi](./catcfdi/changes.json),
[sat69b](./sat69b/changes.json) - twelve hours behind. It is the identical
format; the only difference between the paid copy and the free copy is when it
appears.

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

One checkout, five steps, no automation, and about **twelve minutes of the
operator's own hands per order**. That cost is paid again for every order, and
it does not go down with volume - there is no self-serve provisioning here and
there is no plan to build any. It is written down because a delivery step
quietly assumed to be free is how a small product starts losing money without
noticing. At $28/month, an order is roughly its own first month of revenue.

1. **Create the private repository.** *(~3 min)*
   `latam-gov-diffs-<product>-<short buyer ref>` under the same GitHub account,
   private, no description, no topics. Leave it empty - the first nightly run
   fills it, including its `README.md` and `changes.json`.
2. **Give the nightly job a key to it, and add it to the targets.** *(~6 min)*
   There is exactly one secret to edit, `PAID_TARGETS`, and it holds a JSON
   array of objects - one object per repository, so one feed sold twice is two
   objects with the same `feed`.

   ```
   ssh-keygen -t ed25519 -N "" -C "govdiff-bot" -f ./key
   base64 -w0 key          # the value for deploy_key_b64
   ```

   Add `key.pub` to the new repository under **Settings → Deploy keys → Add
   deploy key**, with **Allow write access** ticked. Then append one object to
   the `PAID_TARGETS` repository secret:

   ```json
   [
     {
       "feed": "cclasstrib",
       "repo": "git@github.com:<owner>/<the new repo>.git",
       "deploy_key_b64": "<the base64 blob>"
     }
   ]
   ```

   The private key is base64-encoded because a multi-line PEM does not survive
   being pasted into a JSON string in a GitHub secret. Delete `key` and
   `key.pub` from the machine afterwards; the secret is now the only copy, and
   a lost key costs one minute to replace.

   When the secret is absent or empty the nightly prints *"no paid targets
   configured - skipping"* and carries on, so an archive with no subscribers
   runs green.
3. **Send the invite.** *(~2 min)* GitHub → repository → Settings →
   Collaborators → add the username or email the buyer gave at checkout,
   **Read** permission. GitHub sends the invitation itself; no message from us
   is needed and none is sent.
4. **Record the order** *(~1 min)* in the private ledger: product, date, buyer's
   GitHub handle, repository name, Stripe reference. Nothing else about the
   buyer is kept.
5. **On cancellation - the invite is revoked.** *(~2 min)* Stripe reports the
   cancellation; at the end of the paid period the collaborator is removed, the
   target's object is deleted from `PAID_TARGETS`, and the private repository is
   archived. Anything already cloned stays cloned; nothing is clawed back, and
   there is nothing to uninstall. The public archive is still there, free,
   twelve hours behind.

**A note on what the operator's logs can see.** The nightly never prints a
subscriber's repository URL. Each target appears in the run log and in the run's
manifest as `target-<8 hex characters>`, a hash of its URL. This repository
becomes public on 2026-09-22 and a public repository's Actions logs are public
with it; a buyer's private repository name is not ours to publish.

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
