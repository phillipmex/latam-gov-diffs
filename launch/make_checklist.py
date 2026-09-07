#!/usr/bin/env python3
"""Generate `launch/checklist.md` - everything only the owner's hands can do.

Run it from anywhere:

    python launch/make_checklist.py            # rewrite launch/checklist.md
    python launch/make_checklist.py --check    # exit 1 if it is out of date
    python launch/make_checklist.py --stdout   # print it instead of writing

Why generate it rather than type it. The checklist's most error-prone section is
the Stripe one: one payment link per buy button has to be created and pasted
onto the offer pages, and the pages already carry the exact button ids the links
belong to. There are four buttons today; there is no list of them anywhere but
the pages, and this script counts them rather than trusting a number in prose.
Typing that list a second time by hand is how a product ships with one button
that silently goes nowhere. So the list is read off the pages themselves, the
same way `tests/test_docs_links.py` reads it, and `tests/test_launch.py` fails
if the committed checklist stops matching what a fresh run produces.

Standard library only - it must run on a bare Python with nothing installed,
which is the state the owner's machine is in at 09:22 on launch morning.
"""

from __future__ import annotations

import argparse
import sys
from html.parser import HTMLParser
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
OFFERS = REPO / "docs" / "offers"
OUTPUT = REPO / "launch" / "checklist.md"

LAUNCH_DATE = "2026-09-22"
STRIPE_DATE = "2026-09-19"
FIRST_CRON_DATE = "2026-09-08"
TIMEBOX_DATE = "2026-09-26"
VIEWER_URL = "https://phillipmex.github.io/latam-gov-diffs/"
REPO_URL = "https://github.com/phillipmex/latam-gov-diffs"
RAW_BASE = "https://raw.githubusercontent.com/phillipmex/latam-gov-diffs/main/"
SMOKE_REPO = "phillipmex/govdiff-paid-smoke"

# No commit counts are written into the checklist, deliberately. It is committed
# and `tests/test_launch.py` compares it against a fresh run, so any number that
# moved with every commit would fail the suite the next time anything was
# pushed. The checklist prints the command that gives the live number instead.

# The placeholder every buy button carries until a real Stripe link replaces it.
# Kept identical to `tests/test_docs_links.py`, which enforces it.
BUY_HREF = "#stripe-pending"


# ------------------------------------------------------- reading the pages


class BuyButtonCollector(HTMLParser):
    """Every `<a class="buy">` on a page, with its href, product id and text.

    This is the same scan `tests/test_docs_links.py` performs. It is repeated
    here rather than imported because this script has to run standalone, with
    no pytest and no `src/` on the path.
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.buttons: list[dict[str, str]] = []
        self._open: dict[str, str] | None = None
        # The price is not inside the button - it is in the `<span class="amount">`
        # above it, which is where a reader sees it. The last one seen before a
        # button is that button's price; the pages have been laid out that way
        # since day 6 and `tests/test_launch.py` checks the answer is not blank.
        self._amount = ""
        self._in_amount = False

    def handle_starttag(self, tag: str, attrs) -> None:
        mapping = {name: (value or "") for name, value in attrs}
        classes = mapping.get("class", "").split()
        if "amount" in classes:
            self._in_amount = True
            self._amount = ""
            return
        if tag != "a" or "buy" not in classes:
            return
        self._open = {
            "href": mapping.get("href", ""),
            "product": mapping.get("data-product", ""),
            "price": self._amount,
            "text": "",
        }

    handle_startendtag = handle_starttag

    def handle_data(self, data: str) -> None:
        if self._in_amount:
            self._amount += data
        if self._open is not None:
            self._open["text"] += data

    def handle_endtag(self, tag: str) -> None:
        if self._in_amount:
            self._amount = " ".join(self._amount.split())
            self._in_amount = False
            return
        if tag == "a" and self._open is not None:
            self._open["text"] = " ".join(self._open["text"].split())
            self.buttons.append(self._open)
            self._open = None


def buy_buttons() -> list[dict[str, str]]:
    """Every buy button in `docs/offers/`, sorted by product id."""
    found: list[dict[str, str]] = []
    for page in sorted(OFFERS.glob("*.html")):
        collector = BuyButtonCollector()
        collector.feed(page.read_text(encoding="utf-8"))
        for button in collector.buttons:
            button["page"] = "docs/offers/" + page.name
            found.append(button)
    return sorted(found, key=lambda b: (b["product"], b["page"]))


def price_of(button: dict[str, str]) -> str:
    """The price shown above the button, or an empty string if the page has none."""
    return button.get("price", "")


# ------------------------------------------------------------- the document


def render() -> str:
    buttons = buy_buttons()
    pending = [b for b in buttons if b["href"] == BUY_HREF]

    out: list[str] = []
    add = out.append

    # (section title, owner minutes, the aside under the number). The total at
    # the bottom is summed from this rather than typed, for the same reason the
    # Stripe rows are counted rather than typed.
    budget: list[tuple[str, int, str]] = []

    def costs(title: str, minutes: int, note: str = "") -> None:
        budget.append((title, minutes, note))

    add("# Launch checklist - %s" % LAUNCH_DATE)
    add("")
    add("**Generated by `launch/make_checklist.py`. Do not edit by hand** - edit the")
    add("script, re-run it, and commit both. `tests/test_launch.py` fails if this file")
    add("and a fresh run disagree.")
    add("")
    add("Every item below needs the owner's own logged-in accounts. None of it can be")
    add("done by an agent, and none of it has been done: this is the whole of the")
    add("manual work between a finished repository and a live product. Each section")
    add("says what it costs in the owner's own minutes, and the total is at the bottom.")
    add("")
    add("The dates: Stripe links around **%s**, the public flip and the post on"
        % STRIPE_DATE)
    add("**%s**, and a hard timebox of **%s** - after that the project stops"
        % (LAUNCH_DATE, TIMEBOX_DATE))
    add("whether or not every box below is ticked.")
    add("")

    # ------------------------------------------------------- the smoke repo
    add("## 1. Delete the day-9 smoke repository")
    add("")
    add("`%s` was created on day 9 to prove the paid push against a" % SMOKE_REPO)
    add("real private GitHub repository over a real deploy key, and it worked. It now")
    add("holds a copy of one feed's slice and a deploy key that nothing uses. It is")
    add("private and it stays private, but it is a loose end with a key in it.")
    add("")
    add("- [ ] github.com/%s → Settings → Danger Zone → **Delete this repository**"
        % SMOKE_REPO)
    add("- [ ] the deploy key dies with it; nothing else refers to that repository")
    add("")
    costs("Delete the day-9 smoke repository", 2)
    add("**2 minutes.** Can be done today; nothing depends on it.")
    add("")

    # ------------------------------------------------- the first cron cycle
    add("## 2. Watch the first unattended nightly (%s)" % FIRST_CRON_DATE)
    add("")
    add("Every run so far has been dispatched by hand. The two crons - 06:15 UTC")
    add("harvest, 18:15 UTC publish - have never fired on their own. The first time")
    add("they do is %s, and that is worth fifteen minutes of attention once."
        % FIRST_CRON_DATE)
    add("")
    add("After **18:30 UTC** on %s, from inside the clone:" % FIRST_CRON_DATE)
    add("")
    add("```sh")
    add("gh run list --workflow nightly.yml --event schedule --limit 4")
    add("gh run view <harvest-run-id>          # the 06:15 one")
    add("gh run view <publish-run-id> --log    # the 18:15 one")
    add("```")
    add("")
    add("What a good night looks like:")
    add("")
    add("- [ ] **two** runs listed with event `schedule`, one near 06:15 and one near 18:15")
    add("- [ ] both say `success`")
    add("- [ ] the harvest log has one line per feed and no `HELD BACK` warning")
    add("- [ ] the harvest log ends with an artifact named `archive-<the date>` uploaded")
    add("- [ ] the publish log either commits, or says the derived files were left alone")
    add("")
    add("If nothing has appeared by 18:45, that is usually not a failure: GitHub delays")
    add("scheduled runs under load, sometimes by half an hour. Check again within the")
    add("hour before touching anything. If a run really is missing, dispatch it by hand")
    add("- Actions → Nightly → Run workflow, with `job` set to the one that did not")
    add("fire - and the day is saved: the artifact holds the morning's work for 7 days.")
    add("")
    costs("Watch the first unattended nightly", 15, "once, on %s" % FIRST_CRON_DATE)
    add("**15 minutes, once.**")
    add("")

    # ------------------------------------------------------- author identity
    add("## 3. Decide: the commit author on every commit becomes public")
    add("")
    add("This one is a decision, not a task, and it has to be made **before** the flip")
    add("because it cannot be made after it.")
    add("")
    add("Every commit in the history was made by one of two identities: the owner's")
    add("own git identity, which carries a personal outlook.com mailbox, and")
    add("`govdiff-bot`, which carries a `users.noreply.github.com` address and is fine.")
    add("Those names and addresses are stored inside the commit objects. They show on")
    add("every commit page, in the API and in every clone, and the project's faceless")
    add("rule cannot reach them: no edit to any file changes what is already committed.")
    add("Nothing in the *content* of the repository names a person - that was checked")
    add("on day 10, file by file. This is the one remaining exposure, and it is in the")
    add("history. To see the current count:")
    add("")
    add("```sh")
    add("git log --format='%an <%ae>' | sort | uniq -c")
    add("```")
    add("")
    add("**Option A - accept it (0 minutes).** The account handle is already public by")
    add("design: it is in the repository URL, the Pages domain, the PyPI and npm owner")
    add("and the trusted-publisher configuration. What the history adds beyond that is")
    add("one mailbox.")
    add("")
    add("**Option B - rewrite before the flip (about 10 minutes).** Set a GitHub noreply")
    add("address on the account, then squash the history to a single commit or rewrite")
    add("the author on all of them, and force-push while the repository is still")
    add("private. Two things to know before choosing it: the `govdiff-bot` commits are")
    add("part of the same history and go with it, and the dated record of when each")
    add("snapshot landed goes with it too. `govdiff attest` does not read git - its")
    add("evidence is the snapshots and their `meta.json` - so attestation is unaffected")
    add("either way.")
    add("")
    add("- [ ] decided: **A, accept as is**")
    add("- [ ] decided: **B, rewrite before the flip** - and done, while still private")
    add("")
    costs("Decide the commit-author question", 5, "10 more only if the answer is B")
    add("**5 minutes to decide. 10 more only if the answer is B.**")
    add("")

    # ---------------------------------------------------------------- Stripe
    add("## 4. Stripe - %d payment link%s" % (len(buttons), "" if len(buttons) == 1 else "s"))
    add("")
    add("Create one payment link per row at dashboard.stripe.com, then replace that")
    add("button's `href` on the page named beside it. The `data-product` value is the")
    add("id to search the page for; there is exactly one button per id.")
    add("")
    add("| # | `data-product` | price | page | button text |")
    add("|--:|---|---|---|---|")
    for number, button in enumerate(buttons, start=1):
        add(
            "| %d | `%s` | %s | `%s` | %s |"
            % (
                number,
                button["product"],
                price_of(button) or "-",
                button["page"],
                button["text"] or "-",
            )
        )
    add("")
    if pending:
        add(
            "All %d still point at `%s`, the deliberate placeholder. A button whose "
            "`href` is still that fragment on launch morning is a button that takes "
            "money from nobody." % (len(pending), BUY_HREF)
        )
    else:
        add("Every button already carries a real link. Nothing to do here.")
    add("")
    add("**Do not search-and-replace across the repository.** `%s` appears in" % BUY_HREF)
    add("two further places - `docs/offers/TEMPLATE.md` and `docs/paid.md` - where it is")
    add("the documented example, not a button. There are exactly %d paste points and"
        % len(buttons))
    add("they are the %d rows above." % len(buttons))
    add("")
    add("`docs/paid.md` says the visible text is replaced with the price at the same")
    add("time. The test suite allows both states - the placeholder, or an `https://`")
    add("Stripe link with a price on it - and rejects anything else, so a half-done")
    add("paste is caught by `pytest` rather than by a customer.")
    add("")
    add("- [ ] every link created, in **live** mode, not test mode")
    add("- [ ] every `href` replaced and the visible text changed to the price")
    add("- [ ] each link opened once and checked against its price above")
    add("- [ ] `python -m pytest -q` green, `python launch/make_checklist.py` re-run, and")
    add("      the pages, this checklist and the script committed together")
    add("")
    costs("Stripe payment links", 5 * len(buttons) + 10,
          "%d links at 5 minutes, plus the account itself" % len(buttons))
    add("**About 5 minutes per link, plus about 10 for the Stripe account itself.**")
    add("")

    # ------------------------------------------------------------ publishing
    add("## 5. Publishing - PyPI and npm trusted publishers")
    add("")
    add("From day 4. Register both trusted publishers **before** pushing any tag;")
    add("`release.yml` carries no token and cannot publish without them.")
    add("")
    add("| step | where | what to enter | min |")
    add("|---|---|---|--:|")
    add(
        "| Create two environments | GitHub, repo Settings, Environments | names "
        "exactly `pypi` and `npm`; no secrets, no reviewers | 2 |"
    )
    add(
        "| PyPI pending publisher | pypi.org, Account, Publishing, add a *pending* "
        "publisher | project `govdiff`, owner `phillipmex`, repository "
        "`latam-gov-diffs`, workflow `release.yml`, environment `pypi` | 5 |"
    )
    add(
        "| npm trusted publisher | npmjs.com, the `govdiff` package, Settings, "
        "Trusted publisher | the same four values, environment `npm` | 5 |"
    )
    add(
        "| *only if npm refuses because the package does not exist yet* | a terminal "
        "| `cd js` then `npm publish --access public` once by hand (2FA prompt), then "
        "set the trusted publisher on the now-existing package | +5 |"
    )
    add("")
    add("- [ ] environments `pypi` and `npm` created")
    add("- [ ] PyPI pending publisher registered")
    add("- [ ] npm trusted publisher registered (or the one manual publish done)")
    add("")
    costs("PyPI and npm trusted publishers", 12, "5 more if npm needs a manual first publish")
    add("**About 12 minutes, 17 if npm needs the manual first publish.** Can be done on")
    add("any earlier day; nothing here needs the repository to be public.")
    add("")

    # ----------------------------------------------------------- the flip
    add("## 6. The public flip")
    add("")
    add("The repository is private until this moment. Nothing above depends on it")
    add("being public, and nothing below works until it is.")
    add("")
    add("- [ ] Settings \u2192 General \u2192 Danger Zone \u2192 **Change visibility \u2192 Public**")
    add("- [ ] Settings \u2192 Pages \u2192 **Deploy from a branch**, branch `main`, folder `/docs`")
    add("- [ ] wait for the first Pages build, then open %s" % VIEWER_URL)
    add("- [ ] check one offer page and one diff deep-link actually load")
    add("")
    add(
        "**About 3 minutes.** Note that Actions logs and artifacts become public at "
        "the same moment. The nightly never prints a subscriber's repository URL - "
        "targets are logged as `target-<hash>` - but this is the day that starts "
        "mattering. Actions minutes also stop being billed here: a public "
        "repository's runners are free, so the roughly 60 minutes a month the two "
        "windows use becomes nothing."
    )
    add("")
    costs("The public flip and Pages", 3)

    # ------------------------------------------------------------- the tag
    add("## 7. Tag `v0.1.0`")
    add("")
    add("The tag is what publishes. `release.yml` builds the wheel and the sdist,")
    add("checks the sdist carries none of the archive, publishes to PyPI through the")
    add("`pypi` environment and then npm through `npm`. It cannot run before \u00a75 is")
    add("done, and there is no token to fall back on.")
    add("")
    add("```sh")
    add("git tag v0.1.0")
    add("git push origin v0.1.0")
    add("```")
    add("")
    add("- [ ] `git tag v0.1.0` and `git push origin v0.1.0`")
    add("- [ ] `release.yml` went green, both jobs")
    add("- [ ] the PyPI page and the npm page both show 0.1.0")
    add("")
    costs("Tag v0.1.0 and watch the release", 1)
    add("**1 minute to push, a few more watching it.**")
    add("")

    # ------------------------------------------------------- the smoke test
    add("## 8. The post-flip smoke test")
    add("")
    add("Six checks, in this order. Every one of them fails while the repository is")
    add("private, which is why they belong after \u00a76 and not before it. All six were")
    add("proved on day 10 against a built wheel and a packed tarball on a local")
    add("server; what cannot be tested before the flip is the public URLs themselves.")
    add("")
    add("| # | check | expected |")
    add("|--:|---|---|")
    add("| 1 | open `%sdocs/index.json` | the JSON index, three feeds |" % RAW_BASE)
    add("| 2 | open %s | the viewer, three feed cards |" % VIEWER_URL)
    add("| 3 | click into a feed, then into one change | the URL gains "
        "`#feed=...&from=...&to=...` and the records render |")
    add("| 4 | add `%sfeed.xml` to any feed reader | the change history, newest first |"
        % VIEWER_URL)
    add("| 5 | `pip install govdiff` then `govdiff --version` | `govdiff 0.1.0` |")
    add("| 6 | `npx govdiff feeds` | a three-row table: catcfdi, cclasstrib, sat69b |")
    add("")
    add("Two more worth doing once, because they are the day-5 defect and its fix:")
    add("")
    add("- [ ] `govdiff status` in a directory that is *not* a checkout prints the")
    add("      no-archive message naming all three ways to point at one - not a crash,")
    add("      and not a guess at site-packages")
    add("- [ ] `govdiff --repo <a clone> status` prints the three-feed table, and so")
    add("      does `govdiff status --repo <a clone>`")
    add("")
    add("Check 1 is the one that matters most: `%s` is the base URL both" % RAW_BASE)
    add("clients default to, so if it 404s then every installed copy of both packages")
    add("is broken, however good the Pages site looks.")
    add("")
    costs("The post-flip smoke test", 10)
    add("**About 10 minutes.**")
    add("")

    # ---------------------------------------------------------- paid targets
    add("## 9. Paid delivery, ready but empty")
    add("")
    add(
        "Nothing to do until the first order. The `PAID_TARGETS` secret does not "
        "exist yet, and the nightly prints *\"no paid targets configured - "
        "skipping\"* and stays green without it. `docs/paid.md` has the five "
        "fulfilment steps and their honest cost, about twelve minutes per order."
    )
    add("")
    add("- [ ] read `docs/paid.md` \u00a7 Fulfilment once, before the first order arrives")
    add("")
    costs("Read the fulfilment steps once", 2)
    add("**2 minutes of reading.**")
    add("")

    # ----------------------------------------------------------------- post
    add("## 10. The post")
    add("")
    add("- [ ] `launch/show-hn.md`, posted at news.ycombinator.com/submit")
    add("- [ ] title pasted exactly; it is already inside Hacker News' 80-character limit")
    add("- [ ] both links in the body open: %s and %s" % (REPO_URL, VIEWER_URL))
    add("- [ ] posted **after** the flip, the Pages build and the tag, not before")
    add("- [ ] then stay at the keyboard for an hour or two and answer questions")
    add("")
    costs("Post it and answer the first questions", 10, "the thread itself is open-ended")
    add("**10 minutes to post.** The thread is open-ended and is not counted below.")
    add("")

    # ------------------------------------------------------------- ordering
    add("## Order of operations")
    add("")
    add("1. delete the smoke repository (\u00a71) - any day")
    add("2. watch the first unattended nightly (\u00a72) - %s only" % FIRST_CRON_DATE)
    add("3. answer the commit-author question (\u00a73) - **before** \u00a76, not after")
    add("4. Stripe links created, pasted and committed (\u00a74) - around %s" % STRIPE_DATE)
    add("5. trusted publishers registered (\u00a75) - any earlier day")
    add("6. repository made public and Pages enabled (\u00a76)")
    add("7. `v0.1.0` tagged and the release workflow green (\u00a77)")
    add("8. the six smoke checks (\u00a78)")
    add("9. Show HN posted (\u00a710)")
    add("")
    add(
        "Steps 1 to 5 can all happen before launch week. Steps 6 to 9 belong to %s "
        "itself and want about half an hour together, in that order." % LAUNCH_DATE
    )
    add("")

    # -------------------------------------------------------------- the bill
    add("## What it costs the owner")
    add("")
    add("| \u00a7 | step | min |")
    add("|--:|---|--:|")
    for number, (title, minutes, note) in enumerate(budget, start=1):
        add("| %d | %s%s | %d |" % (number, title, " *(%s)*" % note if note else "", minutes))
    total = sum(minutes for _, minutes, _ in budget)
    add("| | **total** | **%d** |" % total)
    add("")
    add("**About %d minutes of the owner's own hands**, spread over %s to %s, of which"
        % (total, FIRST_CRON_DATE, LAUNCH_DATE))
    add("roughly half an hour is on launch day itself. Everything else in this project")
    add("is already done.")
    add("")
    return "\n".join(out) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true",
                        help="exit 1 if the committed checklist is out of date")
    parser.add_argument("--stdout", action="store_true",
                        help="print the checklist instead of writing it")
    args = parser.parse_args(argv)

    body = render()

    if args.stdout:
        sys.stdout.write(body)
        return 0

    if args.check:
        if not OUTPUT.exists():
            print("%s does not exist - run this script" % OUTPUT.name)
            return 1
        if OUTPUT.read_text(encoding="utf-8") != body:
            print("%s is out of date - re-run this script and commit it" % OUTPUT.name)
            return 1
        print("%s is up to date" % OUTPUT.name)
        return 0

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(body)
    print("wrote %s (%d bytes)" % (OUTPUT.name, len(body.encode("utf-8"))))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
