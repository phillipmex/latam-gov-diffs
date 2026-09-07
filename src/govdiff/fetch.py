"""Polite, conditional, single-shot fetching with anti-bot detection.

Rules are baked in here on purpose, so no caller can opt out of them:
  * plain unauthenticated GET with an ordinary browser User-Agent
  * timeout 40 s, at most one retry after 30 s, and only for transport faults
  * 403 / 429 / 503, or a challenge marker in the body, raises SourceChallenged
    and the run for that feed stops - there is no proxy or render fallback
"""

from __future__ import annotations

import hashlib
import json
import re
import time
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path

import requests

from govdiff.config import FETCH_MAX_BYTES, repo_root
from govdiff.errors import SourceChallenged, SourceTooLarge

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
)
TIMEOUT = 40
RETRY_AFTER_SECONDS = 30

CHALLENGE_STATUSES = frozenset({403, 429, 503})

# Substrings that mark an interstitial rather than the document we asked for.
# Matched case-insensitively against the first 8 KB of a textual body.
#
# These are deliberately the widget and script markers, not the bare words
# "captcha" or "challenge": the NF-e portal's own navigation menu links to a
# page called consultaRecaptcha.aspx, and a loose match reads that ordinary
# listing page as a wall.
CHALLENGE_MARKERS = (
    "challenge validation",
    "challenge-platform",
    "__cf_chl",
    "cf-challenge",
    "just a moment",
    "g-recaptcha",
    "recaptcha/api.js",
    "hcaptcha.com/1/api.js",
    "data-sitekey",
    "please enable javascript and cookies to continue",
    "ddos protection by",
    "attention required!",
    "checking your browser before accessing",
)

# Leading bytes of the container formats we fetch; a body starting with one of
# these is a document, not an HTML interstitial.
_BINARY_MAGIC = (b"PK\x03\x04", b"\xd0\xcf\x11\xe0", b"%PDF")

_BODY_SNIFF_BYTES = 8192


@dataclass
class FetchResult:
    url: str
    status: int
    content: bytes | None
    sha256: str | None
    size: int | None
    content_type: str | None
    content_disposition: str | None
    etag: str | None
    last_modified: str | None
    fetched_at: str
    not_modified: bool

    def as_dict(self) -> dict:
        """Metadata only - the body is deliberately left out."""
        out = asdict(self)
        out.pop("content")
        return out


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def looks_binary(body: bytes) -> bool:
    return any(body.startswith(magic) for magic in _BINARY_MAGIC)


def detect_challenge(status: int, headers: dict | None, body: bytes | None) -> str | None:
    """Return a reason string if this response is an anti-bot wall, else None."""
    if status in CHALLENGE_STATUSES:
        return "HTTP %d" % status

    headers = {str(k).lower(): str(v) for k, v in (headers or {}).items()}
    content_type = headers.get("content-type", "").lower()
    if not body:
        return None
    if looks_binary(body):
        return None
    # Only sniff bodies that could plausibly be an interstitial page.
    textual = (
        content_type.startswith("text/")
        or "html" in content_type
        or "json" in content_type
        or not content_type
    )
    if not textual:
        return None
    snippet = body[:_BODY_SNIFF_BYTES].decode("utf-8", errors="replace").lower()
    for marker in CHALLENGE_MARKERS:
        if marker in snippet:
            return "body marker: %s" % marker
    # Proof-of-work walls: a challenge token plus a difficulty parameter.
    if "challenge" in snippet and re.search(r"difficulty\s*['\"]?\s*[:=]\s*\d+", snippet):
        return "body marker: proof-of-work challenge"
    return None


def make_session() -> requests.Session:
    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": USER_AGENT,
            "Accept": "*/*",
            "Accept-Language": "pt-BR,pt;q=0.9,es;q=0.8,en;q=0.7",
        }
    )
    return session


def fetch(
    url: str,
    *,
    state: dict | None = None,
    session: requests.Session | None = None,
    max_bytes: int = FETCH_MAX_BYTES,
    conditional: bool = True,
    method: str = "GET",
    use_etag: bool = True,
) -> FetchResult:
    """Fetch `url` once (plus at most one retry on a transport fault).

    When `state` carries an ETag or Last-Modified from a previous run and
    `conditional` is true, the request is made conditional, and a 304 comes
    back as `not_modified=True` with no body.

    `use_etag=False` drops `If-None-Match` and asks on `Last-Modified` alone.
    A publisher whose ETag does not track the bytes - SAT's SharePoint front
    end mints one from the document GUID and a version counter - would
    otherwise get to answer "unchanged" on the strength of a value that says
    nothing about the file. The ETag is still read from the response and
    recorded either way.
    """
    session = session or make_session()
    headers: dict[str, str] = {}
    if conditional and state:
        if use_etag and state.get("etag"):
            headers["If-None-Match"] = state["etag"]
        if state.get("last_modified"):
            headers["If-Modified-Since"] = state["last_modified"]

    response = _request_once(session, method, url, headers, max_bytes)
    fetched_at = utc_now_iso()

    body = response.content if method.upper() != "HEAD" else b""
    reason = detect_challenge(response.status_code, dict(response.headers), body)
    if reason:
        raise SourceChallenged("%s -> %s" % (url, reason))

    if response.status_code == 304:
        prior = state or {}
        return FetchResult(
            url=url,
            status=304,
            content=None,
            sha256=prior.get("sha256"),
            size=None,
            content_type=response.headers.get("Content-Type"),
            content_disposition=response.headers.get("Content-Disposition"),
            etag=response.headers.get("ETag") or prior.get("etag"),
            last_modified=response.headers.get("Last-Modified") or prior.get("last_modified"),
            fetched_at=fetched_at,
            not_modified=True,
        )

    response.raise_for_status()
    if len(body) > max_bytes:
        raise SourceTooLarge("%s returned %d bytes, ceiling is %d" % (url, len(body), max_bytes))

    return FetchResult(
        url=url,
        status=response.status_code,
        content=body,
        sha256=sha256_hex(body),
        size=len(body),
        content_type=response.headers.get("Content-Type"),
        content_disposition=response.headers.get("Content-Disposition"),
        etag=response.headers.get("ETag"),
        last_modified=response.headers.get("Last-Modified"),
        fetched_at=fetched_at,
        not_modified=False,
    )


def _request_once(session, method, url, headers, max_bytes):
    """One request; one retry after 30 s, and only for a transport fault.

    A challenge status is never retried - retrying a wall is exactly what the
    hard rules forbid.
    """
    try:
        response = session.request(
            method, url, headers=headers, timeout=TIMEOUT, allow_redirects=True
        )
    except (requests.Timeout, requests.ConnectionError):
        time.sleep(RETRY_AFTER_SECONDS)
        response = session.request(
            method, url, headers=headers, timeout=TIMEOUT, allow_redirects=True
        )

    declared = response.headers.get("Content-Length")
    if declared and declared.isdigit() and int(declared) > max_bytes:
        response.close()
        raise SourceTooLarge("%s declares %s bytes, ceiling is %d" % (url, declared, max_bytes))
    return response


def filename_from_disposition(disposition: str | None, fallback: str) -> str:
    """Pull the filename out of a Content-Disposition header, sanitised."""
    if disposition:
        match = re.search(r"filename\*?=(?:UTF-8'')?\"?([^\";]+)\"?", disposition, re.I)
        if match:
            # Keep only the last path component, so a header cannot steer the
            # write out of raw/<feed>/<date>/.
            name = re.split(r"[\\/]", match.group(1).strip())[-1]
            name = re.sub(r"[^A-Za-z0-9._ -]", "_", name).strip(" .")
            if name:
                return name
    return fallback


# ---------------------------------------------------------------------------
# Per-feed state, committed under .state/
# ---------------------------------------------------------------------------


def state_path(feed_id: str, root: Path | None = None) -> Path:
    return (root or repo_root()) / ".state" / ("%s.json" % feed_id)


def load_state(feed_id: str, root: Path | None = None) -> dict:
    path = state_path(feed_id, root)
    if not path.exists():
        return {}
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def save_state(feed_id: str, state: dict, root: Path | None = None) -> Path:
    path = state_path(feed_id, root)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(state, fh, indent=2, ensure_ascii=False, sort_keys=True)
        fh.write("\n")
    return path
