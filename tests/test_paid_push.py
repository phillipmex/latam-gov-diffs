"""`govdiff paid-push`, exercised against a real git repository on this disk.

There is no GitHub account, no deploy key and no network in any of this. The
"subscriber repository" is a bare repository in a temp directory reached over a
`file://` URL, which is why `paidpush._is_local_remote` exists: it is the seam
that makes the paid side of the product testable at all.

What matters commercially is checked here rather than left to the nightly:
that an unsold feed is a success and not an error, that the slice holds exactly
what docs/paid.md lists and nothing from another feed, that a second run with
no new data does not push a pointless commit, and that no log line and no
report field ever carries a subscriber's repository URL.
"""

import json
import subprocess

import pytest

from govdiff.cli import main
from govdiff.paidpush import (
    VOLATILE_STATE_FIELDS,
    PaidPushError,
    _is_local_remote,
    load_targets,
    paid_push,
    render_source_state,
    stage_slice,
    target_label,
    targets_for,
)

from test_changefeed import _diff, _version, archive  # noqa: F401  (shared fixture)


def _bare(tmp_path, name):
    """A bare repository standing in for a subscriber's private repo."""
    path = tmp_path / name
    subprocess.run(
        ["git", "init", "--bare", "--initial-branch", "main", str(path)],
        check=True,
        capture_output=True,
    )
    return path


def _url(path):
    return "file:///" + str(path).replace("\\", "/").lstrip("/")


def _files_in(bare):
    out = subprocess.run(
        ["git", "-C", str(bare), "ls-tree", "-r", "--name-only", "main"],
        capture_output=True,
        text=True,
    )
    return sorted(out.stdout.split())


def _log(bare):
    out = subprocess.run(
        ["git", "-C", str(bare), "log", "--format=%an <%ae> %s", "main"],
        check=True,
        capture_output=True,
        text=True,
    )
    return out.stdout.strip().splitlines()


# ------------------------------------------------------------ target parsing


def test_no_secret_at_all_is_a_success_not_a_failure(monkeypatch):
    monkeypatch.delenv("PAID_TARGETS", raising=False)
    assert load_targets("env") == []


@pytest.mark.parametrize("value", ["", "   ", "[]", "\n"])
def test_an_empty_secret_means_no_targets(monkeypatch, value):
    monkeypatch.setenv("PAID_TARGETS", value)
    assert load_targets("env") == []


def test_a_broken_secret_is_reported_not_ignored(monkeypatch):
    monkeypatch.setenv("PAID_TARGETS", "{not json")
    with pytest.raises(PaidPushError):
        load_targets("env")


def test_a_target_without_a_repo_is_rejected(monkeypatch):
    monkeypatch.setenv("PAID_TARGETS", json.dumps([{"feed": "alpha"}]))
    with pytest.raises(PaidPushError) as excinfo:
        load_targets("env")
    assert "repo" in str(excinfo.value)


def test_targets_are_read_from_a_file_too(tmp_path):
    path = tmp_path / "targets.json"
    path.write_text(
        json.dumps([{"feed": "alpha", "repo": "git@github.com:x/y.git"}]),
        encoding="utf-8",
    )
    targets = load_targets(path)
    assert targets_for("alpha", targets) and targets_for("zulu", targets) == []


@pytest.mark.parametrize(
    "repo,local",
    [
        ("file:///tmp/x.git", True),
        ("/srv/mirrors/x.git", True),
        ("git@github.com:owner/name.git", False),
        ("ssh://git@github.com/owner/name.git", False),
        ("https://github.com/owner/name.git", False),
    ],
)
def test_local_remotes_are_told_apart_from_real_ones(repo, local):
    assert _is_local_remote(repo) is local


# ------------------------------------------------------------------ the slice


def test_the_slice_holds_what_paid_md_lists(tmp_path):
    root = archive(tmp_path)
    assert main(["--repo", str(root), "index"]) == 0
    staging = tmp_path / "slice"
    files = stage_slice("alpha", root, staging)

    assert "README.md" in files
    assert "changes.json" in files
    assert "docs/alpha/feed.xml" in files
    assert any(f.startswith("data/alpha/") for f in files)
    assert any(f.startswith("diffs/alpha/") for f in files)

    # And nothing at all from the feed next door.
    assert not [f for f in files if "zulu" in f]

    doc = json.loads((staging / "changes.json").read_text(encoding="utf-8"))
    assert doc["feed"] == "alpha"


def test_the_slice_carries_the_state_file_when_there_is_one(tmp_path):
    root = archive(tmp_path)
    (root / ".state").mkdir(exist_ok=True)
    (root / ".state" / "alpha.json").write_text("{}\n", encoding="utf-8")
    (root / ".state" / "zulu.json").write_text("{}\n", encoding="utf-8")
    assert main(["--repo", str(root), "index"]) == 0
    files = stage_slice("alpha", root, tmp_path / "slice")
    assert ".state/alpha.json" in files
    assert ".state/zulu.json" not in files


def test_the_slice_readme_names_nobody(tmp_path):
    root = archive(tmp_path)
    assert main(["--repo", str(root), "index"]) == 0
    staging = tmp_path / "slice"
    stage_slice("alpha", root, staging)
    readme = (staging / "README.md").read_text(encoding="utf-8")
    assert "latam-gov-diffs maintainers" in readme
    assert "@" not in readme.replace("latam-gov-diffs", "")


# ------------------------------------------------------------------- pushing


def test_an_unsold_feed_is_skipped_and_succeeds(tmp_path):
    root = archive(tmp_path)
    report = paid_push("alpha", root, targets=[])
    assert report["outcome"] == "no-targets"
    assert report["target_count"] == 0


def test_a_dry_run_touches_no_remote_and_prints_a_tree(tmp_path):
    root = archive(tmp_path)
    assert main(["--repo", str(root), "index"]) == 0
    bare = _bare(tmp_path, "sub.git")
    targets = [{"feed": "alpha", "repo": _url(bare), "deploy_key_b64": ""}]
    report = paid_push("alpha", root, targets=targets, dry_run=True)

    assert report["outcome"] == "dry-run"
    assert [t["outcome"] for t in report["targets"]] == ["dry-run"]
    assert {entry["path"] for entry in report["tree"]} == set(report["files"])
    assert all(entry["bytes"] >= 0 for entry in report["tree"])
    # The remote is untouched: an empty bare repository has no branches.
    assert _files_in(bare) == []


def test_a_push_lands_the_slice_in_the_subscribers_repository(tmp_path):
    root = archive(tmp_path)
    assert main(["--repo", str(root), "index"]) == 0
    bare = _bare(tmp_path, "sub.git")
    targets = [{"feed": "alpha", "repo": _url(bare), "deploy_key_b64": ""}]

    report = paid_push("alpha", root, targets=targets, message="chore(alpha): harvest")
    assert report["outcome"] == "success"
    assert [t["outcome"] for t in report["targets"]] == ["success"]

    landed = _files_in(bare)
    assert "README.md" in landed
    assert "changes.json" in landed
    assert any(f.startswith("diffs/alpha/") for f in landed)
    assert not [f for f in landed if "zulu" in f]

    assert _log(bare) == [
        "govdiff-bot <govdiff-bot@users.noreply.github.com> chore(alpha): harvest"
    ]


def test_a_second_push_with_nothing_new_makes_no_commit(tmp_path):
    root = archive(tmp_path)
    assert main(["--repo", str(root), "index"]) == 0
    bare = _bare(tmp_path, "sub.git")
    targets = [{"feed": "alpha", "repo": _url(bare), "deploy_key_b64": ""}]

    paid_push("alpha", root, targets=targets, message="one")
    again = paid_push("alpha", root, targets=targets, message="two")
    assert [t["outcome"] for t in again["targets"]] == ["unchanged"]
    assert len(_log(bare)) == 1


def test_a_night_that_only_re_fetched_makes_no_commit(tmp_path):
    """The production case the file:// test above could not see.

    Day 9 found this on a real run: two harvests two minutes apart, nothing
    moved at the publisher, and the subscriber still got a second commit and a
    second GitHub notification - because `.state/<feed>.json` records
    `last_fetched_at`, which every run rewrites. docs/paid.md sells the
    notification as the alert and promises a night with no change makes no
    commit, so the staged copy drops the fields that describe the run.
    """
    root = archive(tmp_path)
    assert main(["--repo", str(root), "index"]) == 0
    state = root / ".state" / "alpha.json"
    state.parent.mkdir(exist_ok=True)
    state.write_text(
        json.dumps(
            {
                "feed": "alpha",
                "last_fetched_at": "2026-09-07T06:15:00+00:00",
                "last_result": "unchanged",
                "last_error": None,
                "sha256": "abc123",
                "version_id": "2026-09-01-abc123",
                "row_count": 3,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    bare = _bare(tmp_path, "sub.git")
    targets = [{"feed": "alpha", "repo": _url(bare), "deploy_key_b64": ""}]

    paid_push("alpha", root, targets=targets, message="one")

    # The next night: same bytes at the publisher, a new fetch timestamp.
    moved = json.loads(state.read_text(encoding="utf-8"))
    moved["last_fetched_at"] = "2026-09-08T06:15:04+00:00"
    state.write_text(json.dumps(moved, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    again = paid_push("alpha", root, targets=targets, message="two")
    assert [t["outcome"] for t in again["targets"]] == ["unchanged"]
    assert len(_log(bare)) == 1


def test_a_new_version_still_reaches_the_subscriber_through_state(tmp_path):
    """Dropping the run fields must not also drop the ones that matter."""
    root = archive(tmp_path)
    assert main(["--repo", str(root), "index"]) == 0
    state = root / ".state" / "alpha.json"
    state.parent.mkdir(exist_ok=True)
    base = {
        "feed": "alpha",
        "last_fetched_at": "2026-09-07T06:15:00+00:00",
        "last_result": "unchanged",
        "sha256": "abc123",
        "version_id": "2026-09-01-abc123",
        "row_count": 3,
    }
    state.write_text(json.dumps(base, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    bare = _bare(tmp_path, "sub.git")
    targets = [{"feed": "alpha", "repo": _url(bare), "deploy_key_b64": ""}]
    paid_push("alpha", root, targets=targets, message="one")

    moved = dict(base, last_fetched_at="2026-09-08T06:15:04+00:00",
                 last_result="new_version", sha256="def456",
                 version_id="2026-09-08-def456", row_count=4)
    state.write_text(json.dumps(moved, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    again = paid_push("alpha", root, targets=targets, message="two")
    assert [t["outcome"] for t in again["targets"]] == ["success"]
    assert len(_log(bare)) == 2


def test_the_staged_state_file_describes_the_source_not_the_run(tmp_path):
    kept = render_source_state(
        {
            "feed": "alpha",
            "source_url": "https://example.invalid/a.csv",
            "etag": "\"x\"",
            "last_modified": "Thu, 03 Sep 2026 15:02:36 GMT",
            "sha256": "abc123",
            "version_id": "2026-09-01-abc123",
            "row_count": 3,
            "version_count": 2,
            "last_fetched_at": "2026-09-07T06:15:00+00:00",
            "last_result": "unchanged",
            "last_error": None,
        }
    )
    doc = json.loads(kept)
    for gone in VOLATILE_STATE_FIELDS:
        assert gone not in doc
    # Everything a subscriber's README promises is still there.
    for held in ("version_id", "sha256", "last_modified", "row_count",
                 "source_url", "etag", "version_count", "feed"):
        assert held in doc
    assert kept.endswith("}\n")


def test_a_new_diff_reaches_the_subscriber(tmp_path):
    root = archive(tmp_path)
    assert main(["--repo", str(root), "index"]) == 0
    bare = _bare(tmp_path, "sub.git")
    targets = [{"feed": "alpha", "repo": _url(bare), "deploy_key_b64": ""}]
    paid_push("alpha", root, targets=targets, message="one")

    _version(root, "alpha", "2026-08-01-ffffffff")
    _diff(
        root,
        "alpha",
        "2026-06-23-cccccccc",
        "2026-08-01-ffffffff",
        added=2,
        changed=0,
        removed=0,
        generated_at="2026-09-07T06:00:00+00:00",
    )
    assert main(["--repo", str(root), "index"]) == 0
    paid_push("alpha", root, targets=targets, message="two")

    landed = _files_in(bare)
    assert "diffs/alpha/2026-06-23-cccccccc__2026-08-01-ffffffff.jsonl" in landed
    assert len(_log(bare)) == 2


def test_a_broken_target_fails_that_feed_and_says_so(tmp_path):
    root = archive(tmp_path)
    assert main(["--repo", str(root), "index"]) == 0
    targets = [
        {
            "feed": "alpha",
            "repo": _url(tmp_path / "does-not-exist.git"),
            "deploy_key_b64": "",
        }
    ]
    report = paid_push("alpha", root, targets=targets)
    assert report["outcome"] == "failure"
    assert report["targets"][0]["outcome"] == "failure"


def test_two_targets_for_one_feed_both_get_it(tmp_path):
    root = archive(tmp_path)
    assert main(["--repo", str(root), "index"]) == 0
    first, second = _bare(tmp_path, "a.git"), _bare(tmp_path, "b.git")
    targets = [
        {"feed": "alpha", "repo": _url(first), "deploy_key_b64": ""},
        {"feed": "alpha", "repo": _url(second), "deploy_key_b64": ""},
        {"feed": "zulu", "repo": _url(_bare(tmp_path, "c.git")), "deploy_key_b64": ""},
    ]
    report = paid_push("alpha", root, targets=targets)
    assert report["outcome"] == "success"
    assert report["target_count"] == 2
    assert _files_in(first) and _files_in(second)


# ------------------------------------------------------- keeping buyers quiet
#
# This repository goes public on 2026-09-22 and a public repository's Actions
# logs and artifacts are public with it. A subscriber's repository URL is not
# ours to publish, so it must not survive into a log line or a report field.


def test_a_target_is_labelled_by_hash_never_by_url():
    repo = "git@github.com:acme-holdings/tax-feed-private.git"
    label = target_label(repo)
    assert label.startswith("target-") and len(label) == len("target-") + 8
    assert "acme" not in label and "github" not in label
    assert target_label(repo) == label  # stable across runs


def test_neither_the_report_nor_the_printed_log_carries_the_url(
    tmp_path, capsys, monkeypatch
):
    root = archive(tmp_path)
    assert main(["--repo", str(root), "index"]) == 0
    bare = _bare(tmp_path, "acme-secret-name.git")
    monkeypatch.setenv(
        "PAID_TARGETS",
        json.dumps([{"feed": "alpha", "repo": _url(bare), "deploy_key_b64": ""}]),
    )
    report_path = tmp_path / "report.json"
    assert (
        main(
            [
                "--repo",
                str(root),
                "paid-push",
                "--feed",
                "alpha",
                "--report",
                str(report_path),
            ]
        )
        == 0
    )

    printed = capsys.readouterr().out
    written = report_path.read_text(encoding="utf-8")
    for haystack in (printed, written):
        assert "acme-secret-name" not in haystack
        assert "file:///" not in haystack
    assert target_label(_url(bare)) in printed


def test_the_cli_says_plainly_when_there_is_nothing_to_do(tmp_path, capsys, monkeypatch):
    root = archive(tmp_path)
    monkeypatch.delenv("PAID_TARGETS", raising=False)
    assert main(["--repo", str(root), "paid-push", "--feed", "alpha"]) == 0
    assert "no paid targets configured" in capsys.readouterr().out


def test_the_cli_exits_nonzero_when_a_push_fails(tmp_path, monkeypatch):
    root = archive(tmp_path)
    assert main(["--repo", str(root), "index"]) == 0
    monkeypatch.setenv(
        "PAID_TARGETS",
        json.dumps(
            [{"feed": "alpha", "repo": _url(tmp_path / "gone.git"), "deploy_key_b64": ""}]
        ),
    )
    assert main(["--repo", str(root), "paid-push", "--feed", "alpha"]) == 1
