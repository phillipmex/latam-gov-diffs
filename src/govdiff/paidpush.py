"""`govdiff paid-push`: put one feed's slice into a subscriber's repository.

A paid feed is an invite to a private GitHub repository (see `docs/paid.md`).
This is the code that fills that repository, once a night, from the morning
harvest - twelve hours before the same diffs reach public `main`.

**One secret, not one workflow edit per sale.** `PAID_TARGETS` holds a JSON
array of objects::

    [
      {"feed": "cclasstrib",
       "repo": "git@github.com:owner/name.git",
       "deploy_key_b64": "<the private key, base64 -w0>"}
    ]

The private key is base64-encoded because a multi-line PEM inside a JSON string
inside a GitHub secret survives exactly one round trip badly. Selling a second
subscription is one edit to that one secret; no workflow change, no new secret,
no redeploy.

**A target that is absent is not an error.** With no secret, or an empty array,
the command prints that there is nothing configured and succeeds - which is the
state of this repository today and on launch day, and it must not fail a
nightly run.

**A target is a fresh clone, not an orphan force-push.** Cloning keeps the
subscriber's commit history, and that history *is* the product: every night's
commit is their alert (paid.md sells GitHub's own notifications) and their
dated record of what moved. Force-pushing one orphan branch every night would
leave a repository with exactly one commit, no history to read, and a "forced
update" in every notification.

**Nothing in the log names a buyer.** This repository goes public on
2026-09-22, and a public repository's Actions logs are public with it. So a
target is written to the log as `target-<sha256[:8]>` of its URL - stable
enough to follow one target across runs, and useless to anybody else. The same
label, and never the URL, is what goes into the run manifest.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import os
import shutil
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from govdiff.changefeed import build_changes_json, build_entries, render_changes_json
from govdiff.config import HEAD_START_HOURS, load_feeds, repo_root
from govdiff.errors import GovDiffError
from govdiff.index import build_index

# The one repository secret. `--targets-json env` reads it from here.
TARGETS_ENV = "PAID_TARGETS"

# The same identity the public commit step uses.
BOT_NAME = "govdiff-bot"
BOT_EMAIL = "govdiff-bot@users.noreply.github.com"

DEFAULT_BRANCH = "main"

# A target's clone only ever needs its newest commit.
CLONE_DEPTH = 1


class PaidPushError(GovDiffError):
    """A target could not be written. Always names the target by its label."""


def target_label(repo: str) -> str:
    """A stable, non-identifying name for one target, safe to print."""
    return "target-%s" % hashlib.sha256(repo.encode("utf-8")).hexdigest()[:8]


def _is_local_remote(repo: str) -> bool:
    """`file://` and plain paths need no ssh key. The tests use them.

    Supporting `file://` is the whole reason `paid-push` is testable without a
    GitHub account: a bare repository in a temp directory is a perfectly good
    remote, and the code path either side of the clone is identical.
    """
    if repo.startswith("file://"):
        return True
    if repo.startswith(("ssh://", "git://", "http://", "https://")):
        return False
    # scp-like: git@github.com:owner/name.git
    if "@" in repo and ":" in repo:
        return False
    return True


def load_targets(source: str | Path | None) -> list[dict]:
    """Read the targets array from a file, or from the environment.

    `source` is a path, or `env` / `env:NAME` for an environment variable.
    Missing, empty, blank and `[]` all mean the same thing: no targets. That is
    a supported state, not a failure.
    """
    raw: str | None
    if source is None or str(source) == "env" or str(source).startswith("env:"):
        name = TARGETS_ENV
        if source is not None and str(source).startswith("env:"):
            name = str(source).split(":", 1)[1] or TARGETS_ENV
        raw = os.environ.get(name)
    else:
        path = Path(source)
        if not path.exists():
            raise PaidPushError("targets file not found: %s" % path)
        raw = path.read_text(encoding="utf-8")

    if raw is None or not raw.strip():
        return []
    try:
        parsed = json.loads(raw)
    except ValueError as exc:
        raise PaidPushError("the paid targets are not valid JSON: %s" % exc) from exc
    if parsed in (None, {}):
        return []
    if not isinstance(parsed, list):
        raise PaidPushError("the paid targets must be a JSON array of objects")

    out = []
    for position, item in enumerate(parsed, start=1):
        if not isinstance(item, dict):
            raise PaidPushError("paid target %d is not an object" % position)
        missing = [k for k in ("feed", "repo") if not item.get(k)]
        if missing:
            raise PaidPushError(
                "paid target %d is missing %s" % (position, ", ".join(missing))
            )
        out.append(
            {
                "feed": str(item["feed"]),
                "repo": str(item["repo"]),
                "deploy_key_b64": item.get("deploy_key_b64") or "",
            }
        )
    return out


def targets_for(feed_id: str, targets: list[dict]) -> list[dict]:
    return [t for t in targets if t["feed"] == feed_id]


# ------------------------------------------------------------------ the slice


def render_target_readme(feed_id: str, index: dict) -> str:
    """The README a subscriber opens first. Short, faceless, and accurate."""
    meta = next((f for f in index["feeds"] if f["id"] == feed_id), {}) or {}
    lines = [
        "# %s - private feed" % feed_id,
        "",
        "%s - %s, %s."
        % (meta.get("title", feed_id), meta.get("publisher", ""), meta.get("country", "")),
        "",
        "This repository carries one feed of the `latam-gov-diffs` archive. It is",
        "rewritten by the harvester once a night, and every night that produced a",
        "change is one commit here - which is also the alert: watch this repository",
        "and GitHub tells you. A night with no change produces no commit.",
        "",
        "**It lands here %d hours before the public archive.**" % HEAD_START_HOURS,
        "",
        "## What is in it",
        "",
        "| path | what |",
        "|---|---|",
        "| `changes.json` | the one file to poll: `latest.to` is the newest version id |",
        "| `data/%s/<version>/` | one Parquet snapshot per published version, with a `meta.json` sidecar |" % feed_id,
        "| `diffs/%s/<from>__<to>.jsonl` | one JSON object per changed record, with a `.summary.json` beside it |" % feed_id,
        "| `.state/%s.json` | what the harvester last saw: version id, sha256, `Last-Modified` |" % feed_id,
        "| `docs/%s/feed.xml` | the same history as an Atom feed, for a feed reader |" % feed_id,
        "",
        "Paths inside `changes.json` are relative to this repository's root.",
        "",
        "## Terms",
        "",
        "`docs/paid.md` in the public archive is the whole and binding description of",
        "what this is: what is included, what is not, support, and refunds. Support is",
        "an issue on this repository, first response within two business days.",
        "",
        "The public archive is at <https://github.com/phillipmex/latam-gov-diffs> and",
        "the viewer at <https://phillipmex.github.io/latam-gov-diffs/>.",
        "",
        "Code MIT. The archived data is public government data, reproduced with",
        "attribution. Operated by the latam-gov-diffs maintainers.",
    ]
    return "\n".join(lines) + "\n"


def _copy_tree(source: Path, destination: Path) -> list[str]:
    copied: list[str] = []
    if not source.exists():
        return copied
    for item in sorted(source.rglob("*")):
        if item.is_dir():
            continue
        relative = item.relative_to(source)
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(item, target)
        copied.append(target.name)
    return copied


def stage_slice(feed_id: str, root: Path, staging: Path, index: dict | None = None) -> list[str]:
    """Lay out exactly what a paid target holds, and return its file list.

    Everything here is already on disk: this makes no network request and reads
    nothing but the archive. `changes.json` is copied from
    `docs/<feed>/changes.json` when `govdiff index` has already written it, and
    generated from the same code path when it has not.
    """
    root = Path(root).resolve()
    index = index or build_index(root)
    feeds = load_feeds(root / "feeds.yaml")
    if feed_id not in feeds:
        raise PaidPushError("unknown feed '%s'" % feed_id)

    staging.mkdir(parents=True, exist_ok=True)

    (staging / "README.md").write_text(
        render_target_readme(feed_id, index), encoding="utf-8", newline="\n"
    )

    _copy_tree(root / "data" / feed_id, staging / "data" / feed_id)
    _copy_tree(root / "diffs" / feed_id, staging / "diffs" / feed_id)

    state = root / ".state" / ("%s.json" % feed_id)
    if state.exists():
        (staging / ".state").mkdir(parents=True, exist_ok=True)
        shutil.copy2(state, staging / ".state" / state.name)

    atom = root / "docs" / feed_id / "feed.xml"
    if atom.exists():
        (staging / "docs" / feed_id).mkdir(parents=True, exist_ok=True)
        shutil.copy2(atom, staging / "docs" / feed_id / "feed.xml")

    published = root / "docs" / feed_id / "changes.json"
    if published.exists():
        shutil.copy2(published, staging / "changes.json")
    else:
        entries = build_entries(root, index)
        (staging / "changes.json").write_text(
            render_changes_json(build_changes_json(feed_id, entries)),
            encoding="utf-8",
            newline="\n",
        )

    return sorted(
        p.relative_to(staging).as_posix() for p in staging.rglob("*") if p.is_file()
    )


# ------------------------------------------------------------------- the push


def _git(args: list[str], cwd: Path, env: dict | None = None) -> str:
    result = subprocess.run(
        ["git"] + args,
        cwd=str(cwd),
        env=env,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        # git's own stderr can carry the remote URL, and this log goes public
        # with the repository on 2026-09-22. Only the subcommand and the exit
        # code are propagated.
        raise PaidPushError("git %s failed (exit %d)" % (args[0], result.returncode))
    return result.stdout


def _ssh_env(key_b64: str, directory: Path) -> dict:
    """An environment whose git speaks ssh with this target's deploy key only."""
    env = dict(os.environ)
    if not key_b64:
        return env
    try:
        key = base64.b64decode(key_b64, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise PaidPushError("deploy_key_b64 is not valid base64: %s" % exc) from exc
    path = directory / "deploy_key"
    path.write_bytes(key if key.endswith(b"\n") else key + b"\n")
    try:
        os.chmod(path, 0o600)
    except OSError:  # pragma: no cover - Windows has no mode bits here
        pass
    env["GIT_SSH_COMMAND"] = (
        "ssh -i %s -o IdentitiesOnly=yes -o StrictHostKeyChecking=accept-new"
        " -o UserKnownHostsFile=%s" % (path, directory / "known_hosts")
    )
    return env


def _replace_working_tree(work: Path, staging: Path) -> None:
    """Make the checkout hold exactly what is staged - no more, no less."""
    for item in sorted(work.iterdir()):
        if item.name == ".git":
            continue
        if item.is_dir():
            shutil.rmtree(item)
        else:
            item.unlink()
    for item in sorted(staging.rglob("*")):
        if item.is_dir():
            continue
        target = work / item.relative_to(staging)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(item, target)


def push_one_target(
    target: dict, staging: Path, message: str, workspace: Path
) -> dict:
    """Clone, replace, commit and push one target. Returns its outcome."""
    label = target_label(target["repo"])
    work = workspace / "work"
    env = None if _is_local_remote(target["repo"]) else _ssh_env(
        target["deploy_key_b64"], workspace
    )

    clone = subprocess.run(
        ["git", "clone", "--depth", str(CLONE_DEPTH), target["repo"], str(work)],
        env=env,
        capture_output=True,
        text=True,
    )
    if clone.returncode != 0:
        raise PaidPushError("%s: clone failed (exit %d)" % (label, clone.returncode))

    branch = _git(["branch", "--show-current"], work, env).strip()
    if not branch:
        # A repository created and never pushed to: HEAD is unborn.
        branch = DEFAULT_BRANCH
        _git(["checkout", "-b", branch], work, env)

    _git(["config", "user.name", BOT_NAME], work, env)
    _git(["config", "user.email", BOT_EMAIL], work, env)

    _replace_working_tree(work, staging)
    _git(["add", "-A"], work, env)

    staged = subprocess.run(
        ["git", "diff", "--cached", "--quiet"], cwd=str(work), env=env
    )
    if staged.returncode == 0:
        return {"target": label, "outcome": "unchanged", "note": "nothing to commit"}

    _git(["commit", "-m", message], work, env)
    _git(["push", "origin", "HEAD:refs/heads/%s" % branch], work, env)
    return {"target": label, "outcome": "success", "note": "pushed to %s" % branch}


def paid_push(
    feed_id: str,
    root: Path | None = None,
    targets: list[dict] | None = None,
    dry_run: bool = False,
    message: str | None = None,
) -> dict:
    """Push one feed's slice to every target configured for it.

    The report is the thing the workflow reads: one outcome per target and one
    overall outcome for the feed. `no-targets` is a success - it is what an
    unsold feed looks like.
    """
    root = Path(root or repo_root()).resolve()
    mine = targets_for(feed_id, targets or [])
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    message = message or "chore(%s): harvest %s" % (feed_id, today)

    report = {
        "feed": feed_id,
        "outcome": "no-targets",
        "target_count": len(mine),
        "targets": [],
        "files": [],
    }

    if not mine and not dry_run:
        return report

    workspace = Path(tempfile.mkdtemp(prefix="govdiff-paid-"))
    try:
        staging = workspace / "slice"
        report["files"] = stage_slice(feed_id, root, staging)

        if dry_run:
            report["outcome"] = "dry-run"
            report["tree"] = [
                {"path": name, "bytes": (staging / name).stat().st_size}
                for name in report["files"]
            ]
            for target in mine:
                report["targets"].append(
                    {"target": target_label(target["repo"]), "outcome": "dry-run", "note": ""}
                )
            return report

        failed = False
        for target in mine:
            per_target = workspace / target_label(target["repo"])
            per_target.mkdir(parents=True, exist_ok=True)
            try:
                report["targets"].append(
                    push_one_target(target, staging, message, per_target)
                )
            except PaidPushError as exc:
                failed = True
                report["targets"].append(
                    {
                        "target": target_label(target["repo"]),
                        "outcome": "failure",
                        "note": str(exc),
                    }
                )
        report["outcome"] = "failure" if failed else "success"
        return report
    finally:
        shutil.rmtree(workspace, ignore_errors=True)
