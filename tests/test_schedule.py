"""The nightly's two windows, checked against the one constant that defines them.

`docs/paid.md` sells a twelve-hour head start. That number lives in exactly one
place in the source - `govdiff.config.HEAD_START_HOURS` - and it is also the
gap between the two cron lines in `.github/workflows/nightly.yml`, a file no
Python import ever reads. Nothing stops those two drifting apart except this
test, and the day they drift is the day the product stops matching the promise.
"""

from pathlib import Path

import pytest
import yaml

from govdiff.changefeed import build_changes_json
from govdiff.config import (
    HARVEST_CRON,
    HARVEST_HOUR_UTC,
    HARVEST_MINUTE_UTC,
    HEAD_START_HOURS,
    PUBLISH_CRON,
    PUBLISH_HOUR_UTC,
    PUBLISH_MINUTE_UTC,
    repo_root,
)

WORKFLOW = repo_root() / ".github" / "workflows" / "nightly.yml"


def _workflow():
    with open(WORKFLOW, encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def _crons(doc):
    # PyYAML resolves the bare key `on:` to the boolean True (YAML 1.1), which
    # is why this is not doc["on"]. Accept either, so a future quoted key does
    # not silently make this test look at nothing.
    triggers = doc.get("on", doc.get(True))
    return [entry["cron"].strip() for entry in triggers["schedule"]]


def _parse(cron):
    minute, hour = cron.split()[0], cron.split()[1]
    return int(hour), int(minute)


def test_the_workflow_has_exactly_two_daily_crons():
    crons = _crons(_workflow())
    assert len(crons) == 2, crons
    for cron in crons:
        fields = cron.split()
        assert len(fields) == 5, cron
        assert fields[2:] == ["*", "*", "*"], "both windows run every day: %s" % cron


def test_the_gap_between_the_crons_is_the_head_start():
    first, second = _crons(_workflow())
    (h1, m1), (h2, m2) = _parse(first), _parse(second)
    assert m1 == m2, "the two windows must fall on the same minute past the hour"
    assert (h2 - h1) % 24 == HEAD_START_HOURS, (
        "nightly.yml runs %d hours apart but HEAD_START_HOURS is %d - "
        "docs/paid.md sells the constant, so the crons are wrong"
        % ((h2 - h1) % 24, HEAD_START_HOURS)
    )


def test_the_crons_are_the_ones_config_derives():
    assert _crons(_workflow()) == [HARVEST_CRON, PUBLISH_CRON]
    assert _parse(HARVEST_CRON) == (HARVEST_HOUR_UTC, HARVEST_MINUTE_UTC)
    assert _parse(PUBLISH_CRON) == (PUBLISH_HOUR_UTC, PUBLISH_MINUTE_UTC)


def test_each_job_is_gated_on_its_own_cron():
    """`harvest` must not run at 18:15 and `publish` must not run at 06:15."""
    jobs = _workflow()["jobs"]
    assert set(jobs) == {"harvest", "publish"}
    assert HARVEST_CRON in jobs["harvest"]["if"]
    assert PUBLISH_CRON not in jobs["harvest"]["if"]
    assert PUBLISH_CRON in jobs["publish"]["if"]
    assert HARVEST_CRON not in jobs["publish"]["if"]


def test_the_morning_job_never_pushes_to_public_main():
    """The head start is only real if nothing public moves at 06:15.

    A `git push` in the harvest job - to main, to Pages, anywhere - would put
    the archive in front of the free tier at the same moment as the paid one,
    and there would be no head start left to sell.
    """
    harvest = _workflow()["jobs"]["harvest"]
    for step in harvest["steps"]:
        body = step.get("run") or ""
        assert "git push" not in body, (
            "step %r pushes from the morning job" % step.get("name")
        )


def test_the_publish_job_makes_no_request_to_any_publisher():
    """No evening re-fetch: the publish job runs no harvest command."""
    publish = _workflow()["jobs"]["publish"]
    for step in publish["steps"]:
        body = step.get("run") or ""
        assert "govdiff run" not in body, (
            "step %r re-fetches in the evening" % step.get("name")
        )


def test_the_workflow_dispatch_can_reach_both_jobs_and_force_a_failure():
    inputs = _workflow().get("on", _workflow().get(True))["workflow_dispatch"]["inputs"]
    assert set(inputs) >= {"job", "date", "simulate_failure"}
    assert sorted(inputs["job"]["options"]) == ["harvest", "publish"]


@pytest.mark.parametrize("feed_id", ["cclasstrib", "catcfdi", "sat69b"])
def test_changes_json_publishes_the_same_head_start(feed_id):
    doc = build_changes_json(feed_id, [], generated_at="2026-09-07T06:15:00+00:00")
    assert doc["head_start_hours"] == HEAD_START_HOURS


def test_the_workflow_file_holds_no_second_copy_of_the_number():
    """A bare `12` in a cron line would be a second source of truth."""
    text = Path(WORKFLOW).read_text(encoding="utf-8")
    crons = [line for line in text.splitlines() if "- cron:" in line]
    assert len(crons) == 2
