"""Every relative link in docs/ resolves, and nothing on the page is fetched.

The site under `docs/` is published to GitHub Pages as-is: there is no build
step, no link rewriting, and nothing that would notice a typo. A dead
`href="./paid.md"` on an offer page is the kind of defect that ships quietly
and is found by a buyer, so it is checked here instead.

Two rules are enforced:

* every relative `href`/`src` in a `docs/**/*.html` page points at a file that
  exists on disk, and stays inside the repository;
* no page pulls a script, stylesheet, font, image or iframe off its own origin.
  Zero external requests has been the rule since day 4 and it is what lets the
  pages work offline and under any Content-Security-Policy.
"""

from __future__ import annotations

from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urlsplit

import pytest

REPO = Path(__file__).resolve().parents[1]
DOCS = REPO / "docs"

# Attributes that make the browser go and get something.
URL_ATTRIBUTES = ("href", "src", "action", "poster")

# Tags whose URL is fetched without the reader clicking anything. An <a href>
# to another site is a link a person chooses to follow; these are not.
SUBRESOURCE_TAGS = ("script", "img", "iframe", "audio", "video", "source", "embed", "object")


class LinkCollector(HTMLParser):
    """Every URL-bearing attribute in the document, with its tag."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.found: list[tuple[str, str, str]] = []

    def handle_starttag(self, tag: str, attrs) -> None:
        mapping = {name: (value or "") for name, value in attrs}
        for attribute in URL_ATTRIBUTES:
            if attribute in mapping and mapping[attribute].strip():
                self.found.append((tag, attribute, mapping[attribute].strip()))

    handle_startendtag = handle_starttag


def _pages() -> list[Path]:
    return sorted(DOCS.rglob("*.html"))


def _links(page: Path) -> list[tuple[str, str, str]]:
    collector = LinkCollector()
    collector.feed(page.read_text(encoding="utf-8"))
    return collector.found


def _is_external(url: str) -> bool:
    parts = urlsplit(url)
    return bool(parts.scheme or parts.netloc)


def _is_in_page(url: str) -> bool:
    """A bare fragment, or a same-page query - nothing to resolve on disk."""
    return url.startswith("#") or url.startswith("?")


def test_there_are_pages_to_check():
    assert _pages(), "no HTML found under docs/"


@pytest.mark.parametrize("page", _pages(), ids=lambda p: p.relative_to(REPO).as_posix())
def test_every_relative_link_resolves(page: Path):
    broken: list[str] = []
    escaped: list[str] = []
    for tag, attribute, url in _links(page):
        if _is_external(url) or _is_in_page(url) or url.startswith("data:"):
            continue
        # Drop the query and the fragment: neither is part of the file name.
        target_name = unquote(urlsplit(url).path)
        if not target_name:
            continue
        target = (page.parent / target_name).resolve()
        try:
            target.relative_to(REPO)
        except ValueError:
            escaped.append("%s <%s %s> %s" % (page.name, tag, attribute, url))
            continue
        if not target.exists():
            broken.append("%s <%s %s=\"%s\"> -> %s" % (page.name, tag, attribute, url, target))
    assert not broken, "dead relative links:\n  " + "\n  ".join(broken)
    assert not escaped, "links pointing outside the repository:\n  " + "\n  ".join(escaped)


@pytest.mark.parametrize("page", _pages(), ids=lambda p: p.relative_to(REPO).as_posix())
def test_no_page_fetches_anything_off_its_own_origin(page: Path):
    offenders = []
    for tag, attribute, url in _links(page):
        if not _is_external(url) or url.startswith("data:"):
            continue
        if tag in SUBRESOURCE_TAGS:
            offenders.append("%s <%s %s=\"%s\">" % (page.name, tag, attribute, url))
        elif tag == "link":
            # <link rel="stylesheet"> and preloads are fetched; rel="alternate"
            # and friends are only advertised.
            offenders.append("%s <link %s=\"%s\">" % (page.name, attribute, url))
    assert not offenders, "external subresources:\n  " + "\n  ".join(offenders)


@pytest.mark.parametrize("page", _pages(), ids=lambda p: p.relative_to(REPO).as_posix())
def test_no_page_loads_an_external_stylesheet_or_font(page: Path):
    text = page.read_text(encoding="utf-8")
    for marker in ("@import url(http", "fonts.googleapis.com", "cdn.jsdelivr.net", "unpkg.com"):
        assert marker not in text, "%s pulls from %s" % (page.name, marker)


# ---------------------------------------------------------------- offer pages
#
# The offer pages are the only part of the site that will ever ask anyone for
# money, so two things about them are asserted rather than eyeballed: that the
# index does not advertise a product it cannot link to, and that every buy
# button is still the placeholder rather than a live checkout. Both are the kind
# of mistake that is invisible in a browser and expensive in public.

OFFERS = DOCS / "offers"

# Every product in docs/paid.md, and the page a reader is sent to for it.
PRODUCT_PAGES = {
    "cclasstrib-monthly": "cclasstrib.html",
    "catalogos-sat-monthly": "catalogos-sat.html",
    "listas-mx-monthly": "listas-mx.html",
    "listas-mx-attestation": "listas-mx.html",
}

# The convention fixed in docs/paid.md. The href is a fragment on the page
# itself, so a button can never be a dead external link or a 404.
BUY_HREF = "#stripe-pending"
BUY_TEXT = "Checkout opens on launch (2026-09-22)"


class BuyButtonCollector(HTMLParser):
    """Every <a class="buy">, with its href, data-product and visible text."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.buttons: list[dict[str, str]] = []
        self._open: dict[str, str] | None = None

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag != "a":
            return
        mapping = {name: (value or "") for name, value in attrs}
        if "buy" not in mapping.get("class", "").split():
            return
        self._open = {
            "href": mapping.get("href", ""),
            "product": mapping.get("data-product", ""),
            "text": "",
        }

    def handle_data(self, data: str) -> None:
        if self._open is not None:
            self._open["text"] += data

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self._open is not None:
            self._open["text"] = " ".join(self._open["text"].split())
            self.buttons.append(self._open)
            self._open = None


def _buy_buttons(page: Path) -> list[dict[str, str]]:
    collector = BuyButtonCollector()
    collector.feed(page.read_text(encoding="utf-8"))
    return collector.buttons


def test_every_advertised_product_has_a_page():
    missing = [name for name in sorted(set(PRODUCT_PAGES.values())) if not (OFFERS / name).exists()]
    assert not missing, "offer pages named in the index do not exist: " + ", ".join(missing)


def test_the_offers_index_links_every_product_and_promises_nothing():
    text = (OFFERS / "index.html").read_text(encoding="utf-8")
    for target in ('href="./cclasstrib.html"', 'href="./catalogos-sat.html"',
                   'href="./listas-mx.html"', 'href="./listas-mx.html#attestation"'):
        assert target in text, "the offers index does not link %s" % target
    # The day-6 placeholders are gone; a page that says "coming day 7" after
    # day 7 is worse than no page at all.
    assert "coming day 7" not in text
    assert 'class="pending"' not in text


@pytest.mark.parametrize("page", sorted(OFFERS.glob("*.html")), ids=lambda p: p.name)
def test_every_buy_button_is_still_the_placeholder(page: Path):
    for button in _buy_buttons(page):
        assert button["href"] == BUY_HREF, "%s: buy button href is %r" % (page.name, button["href"])
        assert button["text"] == BUY_TEXT, "%s: buy button text is %r" % (page.name, button["text"])
        assert button["product"] in PRODUCT_PAGES, (
            "%s: unknown data-product %r" % (page.name, button["product"])
        )


def test_each_priced_product_has_exactly_one_buy_button_somewhere():
    seen: dict[str, list[str]] = {}
    for page in sorted(OFFERS.glob("*.html")):
        for button in _buy_buttons(page):
            seen.setdefault(button["product"], []).append(page.name)
    assert sorted(seen) == sorted(PRODUCT_PAGES), "buy buttons found for: %s" % sorted(seen)
    duplicated = {product: pages for product, pages in seen.items() if len(pages) != 1}
    assert not duplicated, "a product is offered twice: %r" % duplicated


@pytest.mark.parametrize("page", sorted(OFFERS.glob("*.html")), ids=lambda p: p.name)
def test_no_offer_page_names_a_person_or_an_address(page: Path):
    """Faceless by rule: the seller is the maintainers, and support is an issue."""
    text = page.read_text(encoding="utf-8")
    assert "@" not in text.replace("&amp;", ""), "%s carries an @ - check for an address" % page.name
    assert "the latam-gov-diffs maintainers" in text
