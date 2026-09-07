"""The launch material: `launch/show-hn.md` and the generated `launch/checklist.md`.

`launch/` is owner-facing. It is not part of the tool, it is not part of the
published site, and it is not in the sdist. What it *is* is the last thing
standing between a finished repository and a live product, so the two things
that can quietly go wrong with it are checked here: a checklist that has drifted
away from the pages it describes, and a post that breaks a rule of the project
(a person's name, a first-person story, a title Hacker News will truncate).
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
LAUNCH = REPO / "launch"
CHECKLIST = LAUNCH / "checklist.md"
SHOW_HN = LAUNCH / "show-hn.md"
SCRIPT = LAUNCH / "make_checklist.py"

sys.path.insert(0, str(LAUNCH))
import make_checklist  # noqa: E402


# --------------------------------------------------------------- the checklist


def test_the_committed_checklist_is_what_the_script_produces():
    assert CHECKLIST.exists()
    assert CHECKLIST.read_text(encoding="utf-8") == make_checklist.render()


def test_regenerating_it_changes_nothing():
    """Run the script for real, as the owner would, and check what it left."""
    result = subprocess.run(
        [sys.executable, str(SCRIPT)], capture_output=True, text=True, cwd=str(REPO)
    )
    assert result.returncode == 0, result.stderr
    # Compared against `render()` rather than a snapshot taken a moment earlier,
    # so the test says the same thing whatever order the suite runs in.
    assert CHECKLIST.read_text(encoding="utf-8") == make_checklist.render()


def test_the_check_flag_agrees():
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--check"],
        capture_output=True,
        text=True,
        cwd=str(REPO),
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_every_buy_button_on_every_offer_page_is_in_the_checklist():
    """The list is read off the pages, so it cannot be short by one."""
    buttons = make_checklist.buy_buttons()
    assert buttons, "no buy buttons found in docs/offers - the scan is broken"
    text = CHECKLIST.read_text(encoding="utf-8")
    for button in buttons:
        assert "`%s`" % button["product"] in text
        assert make_checklist.price_of(button), (
            "%s has no price beside it on %s" % (button["product"], button["page"])
        )
        assert make_checklist.price_of(button) in text


def test_the_checklist_agrees_with_the_link_test_about_the_products():
    """Two independent scans of the same pages must find the same ids."""
    from test_docs_links import PRODUCT_PAGES

    found = {b["product"] for b in make_checklist.buy_buttons()}
    assert found == set(PRODUCT_PAGES)


def test_the_checklist_covers_the_owner_only_steps():
    text = CHECKLIST.read_text(encoding="utf-8")
    for needle in (
        "2026-09-22",           # the date
        "dashboard.stripe.com",  # Stripe
        "pypi.org",              # trusted publishing
        "npmjs.com",
        "environment `pypi`",
        "environment `npm`",
        "git tag v0.1.0",
        "Change visibility → Public",  # the public flip
        "Settings → Pages",            # Pages enablement
        "PAID_TARGETS",
    ):
        assert needle in text, "the checklist never mentions %r" % needle


# ------------------------------------------------------------------ the post


def _section(name: str) -> str:
    text = SHOW_HN.read_text(encoding="utf-8")
    body = text.split("## %s" % name, 1)[1]
    return body.split("\n## ", 1)[0].split("\n---", 1)[0].strip()


def test_the_title_is_a_show_hn_and_fits():
    title = _section("Title")
    assert "\n" not in title
    assert title.startswith("Show HN:")
    assert len(title) <= 80, "%d characters" % len(title)


def test_the_body_is_under_350_words():
    words = _section("Body").split()
    assert len(words) <= 350, "%d words" % len(words)
    assert len(words) > 150, "a Show HN this short says nothing"


def test_the_post_says_what_it_is_and_links_both_places():
    body = _section("Body")
    assert "https://github.com/phillipmex/latam-gov-diffs" in body
    assert "https://phillipmex.github.io/latam-gov-diffs/" in body
    # 69-B is the reason the archive matters; the other two are back-version
    # diffs, and the post has to be straight about the difference.
    assert "69-B" in body
    assert "cClassTrib" in body and "CFDI" in body
    assert "back-versions" in body
    assert "Free" in body or "free" in body


def test_the_post_admits_a_limitation():
    body = _section("Body").lower()
    assert "limit" in body or "cannot" in body


def test_the_post_is_faceless():
    """No person, no first-person story, no address to write to."""
    body = _section("Body")
    assert not re.search(r"\bI\b", body), "the post uses 'I'"
    for word in ("my ", "My ", " me ", "we ", "We ", " our "):
        assert word not in body, "the post uses %r" % word
    assert "@" not in body


@pytest.mark.parametrize("path", sorted(LAUNCH.glob("*.md")))
def test_no_launch_file_carries_a_contact_surface(path):
    text = path.read_text(encoding="utf-8")
    assert not re.search(r"[\w.+-]+@[\w-]+\.[\w.]+", text), "%s holds an email" % path.name


# --------------------------------------------------- launch/ stays where it is


def test_nothing_in_docs_links_to_launch():
    """`launch/` is not published. A link from docs/ would be a 404 on Pages."""
    offenders = []
    for page in sorted((REPO / "docs").rglob("*")):
        if page.suffix.lower() not in (".html", ".md", ".json", ".xml"):
            continue
        if "launch/" in page.read_text(encoding="utf-8", errors="replace"):
            offenders.append(page.relative_to(REPO).as_posix())
    assert not offenders, "docs/ points at launch/: %s" % ", ".join(offenders)


def test_launch_is_pruned_from_the_sdist():
    manifest = (REPO / "MANIFEST.in").read_text(encoding="utf-8")
    assert "prune launch" in manifest
