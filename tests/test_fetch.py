import json

import pytest
import requests

from govdiff.errors import SourceChallenged, SourceTooLarge
from govdiff.fetch import (
    detect_challenge,
    fetch,
    filename_from_disposition,
    load_state,
    save_state,
)

HTML = {"Content-Type": "text/html; charset=utf-8"}

# Trimmed from the real proof-of-work wall the gob.mx page served on 2026-09-06.
POW_BODY = (
    b'<html><head><title>Challenge Validation</title></head><body>'
    b'<script>var challenge="8f2c";var difficulty=15000;solve(challenge,difficulty);</script>'
    b"</body></html>"
)


class FakeResponse:
    def __init__(self, status=200, headers=None, content=b""):
        self.status_code = status
        self.headers = headers or {}
        self.content = content

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError("status %d" % self.status_code)

    def close(self):
        pass


class FakeSession:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def request(self, method, url, headers=None, timeout=None, allow_redirects=True):
        self.calls.append({"method": method, "url": url, "headers": dict(headers or {})})
        return self.response


@pytest.mark.parametrize("status", [403, 429, 503])
def test_challenge_statuses_are_walls(status):
    assert detect_challenge(status, HTML, b"anything") == "HTTP %d" % status


def test_proof_of_work_body_is_a_wall():
    reason = detect_challenge(200, HTML, POW_BODY)
    assert reason is not None
    assert "challenge validation" in reason


def test_cloudflare_interstitial_is_a_wall():
    body = b'<html><body><h1>Just a moment...</h1><div class="cf-challenge"></div></body></html>'
    assert detect_challenge(200, HTML, body) is not None


def test_recaptcha_widget_is_a_wall():
    body = b'<html><body><div class="g-recaptcha" data-sitekey="abc"></div></body></html>'
    assert detect_challenge(200, HTML, body) is not None


def test_ordinary_listing_page_is_not_a_wall():
    # The NF-e portal's own navigation links to consultaRecaptcha.aspx; a loose
    # substring match reads that perfectly normal page as a challenge.
    body = (
        b'<html><body><ul><li><a href="consultaRecaptcha.aspx?tipoConsulta=resumo">'
        b"Consultar NF-e</a></li></ul></body></html>"
    )
    assert detect_challenge(200, HTML, body) is None


def test_spreadsheet_body_is_never_sniffed():
    xlsx = b"PK\x03\x04" + b"captcha challenge difficulty=15000" * 10
    headers = {"Content-Type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"}
    assert detect_challenge(200, headers, xlsx) is None


def test_fetch_raises_on_a_challenged_response():
    session = FakeSession(FakeResponse(200, HTML, POW_BODY))
    with pytest.raises(SourceChallenged):
        fetch("http://example.invalid/doc", session=session)


def test_fetch_sends_stored_validators_and_reports_304():
    session = FakeSession(FakeResponse(304, {"Content-Type": "text/plain"}, b""))
    state = {"etag": '"abc"', "last_modified": "Thu, 22 Jan 2026 22:59:33 GMT", "sha256": "f" * 64}

    result = fetch("http://example.invalid/doc", state=state, session=session)

    sent = session.calls[0]["headers"]
    assert sent["If-None-Match"] == '"abc"'
    assert sent["If-Modified-Since"] == state["last_modified"]
    assert result.not_modified is True
    assert result.content is None
    assert result.sha256 == state["sha256"]


def test_fetch_returns_content_and_metadata():
    headers = {
        "Content-Type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "Content-Disposition": "attachment; filename=cClassTrib 2025-12-12.xlsx",
        "Last-Modified": "Thu, 03 Sep 2026 15:02:36 GMT",
    }
    session = FakeSession(FakeResponse(200, headers, b"PK\x03\x04payload"))

    result = fetch("http://example.invalid/doc", session=session)

    assert result.status == 200
    assert result.size == len(b"PK\x03\x04payload")
    assert result.sha256 and len(result.sha256) == 64
    assert result.last_modified == headers["Last-Modified"]
    assert "content" not in result.as_dict()


def test_declared_size_over_the_ceiling_is_refused():
    session = FakeSession(FakeResponse(200, {"Content-Length": "999999999"}, b""))
    with pytest.raises(SourceTooLarge):
        fetch("http://example.invalid/huge", session=session, max_bytes=1024)


def test_filename_from_disposition():
    header = "attachment; filename=cClassTrib 2025-12-12.xlsx"
    assert filename_from_disposition(header, "fallback.xlsx") == "cClassTrib 2025-12-12.xlsx"
    assert filename_from_disposition(None, "fallback.xlsx") == "fallback.xlsx"
    # A header must not be able to steer the write out of raw/<feed>/<date>/.
    assert filename_from_disposition('attachment; filename="../../evil.xlsx"', "f.xlsx") == "evil.xlsx"
    assert filename_from_disposition('attachment; filename="..."', "f.xlsx") == "f.xlsx"


def test_state_round_trip(tmp_path):
    assert load_state("demo", tmp_path) == {}
    save_state("demo", {"feed": "demo", "sha256": "a" * 64}, tmp_path)
    assert load_state("demo", tmp_path)["sha256"] == "a" * 64
    written = json.loads((tmp_path / ".state" / "demo.json").read_text(encoding="utf-8"))
    assert written["feed"] == "demo"
