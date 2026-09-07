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
