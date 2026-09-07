"""Command line entry point.

`govdiff run|bootstrap|rediff|index|attest|paid-push|status`.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from govdiff import __version__
from govdiff.attest import FEED_ID as ATTEST_FEED
from govdiff.attest import attest
from govdiff.changefeed import write_change_feed
from govdiff.config import load_feeds, resolve_repo_root
from govdiff.errors import AttestationNotPossible, GovDiffError, SourceChallenged
from govdiff.fetch import load_state
from govdiff.index import write_index
from govdiff.paidpush import TARGETS_ENV, load_targets, paid_push
from govdiff.runner import bootstrap_feed, rediff_feed, run_all, run_feed
from govdiff.snapshot import list_versions


def _print_outcome(outcome: dict) -> None:
    note = outcome.get("note")
    if outcome["created"]:
        line = "%s: new version %s (%s rows)" % (
            outcome["feed"],
            outcome["version_id"],
            outcome["row_count"],
        )
    else:
        line = "%s: unchanged (%s)" % (outcome["feed"], note or "already snapshotted")
        if outcome.get("version_id"):
            line += " at %s" % outcome["version_id"]
    print(line)
    summary = outcome.get("diff")
    if summary:
        print(
            "  diff %s -> %s: +%d added, ~%d changed, -%d removed"
            % (
                summary["from_version"],
                summary["to_version"],
                summary["added"],
                summary["changed"],
                summary["removed"],
            )
        )


def cmd_run(args) -> int:
    root = resolve_repo_root(args.root)
    if args.feed:
        outcomes = [run_feed(args.feed, root)]
    else:
        outcomes = run_all(root)
    if not outcomes:
        print("no enabled feed has a parser yet")
    for outcome in outcomes:
        _print_outcome(outcome)
    return 0


def cmd_bootstrap(args) -> int:
    root = resolve_repo_root(args.root)
    report = bootstrap_feed(args.feed, root, delay=args.delay)
    print("listing shows %d %s release(s)" % (report["listed"], args.feed))
    if report.get("note"):
        print(report["note"])
        return 0
    for version in report["versions"]:
        print(
            "  %s  %s  %7d rows  %10d bytes  %5s s  %s"
            % (
                version["published"],
                version["version_id"],
                version["rows"],
                version["bytes"],
                version["fetch_seconds"],
                "new" if version["created"] else "already stored",
            )
        )
    for gone in report.get("missing", []):
        print("  %s  %s  HTTP %s - skipped" % (gone["published"], gone["url"], gone["status"]))
    for summary in report["diffs"]:
        print(
            "  diff %s -> %s: +%d added, ~%d changed, -%d removed"
            % (
                summary["from_version"],
                summary["to_version"],
                summary["added"],
                summary["changed"],
                summary["removed"],
            )
        )
    return 0


def cmd_rediff(args) -> int:
    root = resolve_repo_root(args.root)
    report = rediff_feed(args.feed, root)
    print("%s: %d stored version(s)" % (report["feed"], report["versions"]))
    if report.get("note"):
        print(report["note"])
        return 0
    for summary in report["diffs"]:
        print(
            "  rewrote %s -> %s: +%d added, ~%d changed, -%d removed"
            % (
                summary["from_version"],
                summary["to_version"],
                summary["added"],
                summary["changed"],
                summary["removed"],
            )
        )
    for orphan in report["orphans"]:
        print("  %s covers versions that are no longer neighbours - left as it is" % orphan)
    return 0


def cmd_index(args) -> int:
    root = resolve_repo_root(args.root)
    output = Path(args.output).resolve() if args.output else None
    report = write_index(root, output)
    try:
        shown = report["path"].relative_to(root).as_posix()
    except ValueError:
        shown = str(report["path"])
    print(
        "%s: %d feed(s), %d version(s), %d diff(s) - %s"
        % (
            shown,
            report["feeds"],
            report["versions"],
            report["diffs"],
            "rewritten" if report["changed"] else "unchanged, left alone",
        )
    )
    # The change feed comes out of the same walk and the same command, so the
    # nightly job stays one step. `--output` is the "write the index somewhere
    # else" escape hatch and does not touch the repository, so it skips this.
    if not output and not args.no_change_feed:
        feed_report = write_change_feed(root)
        print(
            "change feed: %d entry(s) - %s"
            % (
                feed_report["entries"],
                (
                    "rewrote " + ", ".join(feed_report["written"])
                    if feed_report["written"]
                    else "unchanged, left alone"
                ),
            )
        )
    return 0


def cmd_attest(args) -> int:
    root = resolve_repo_root(args.root)
    if args.feed != ATTEST_FEED:
        raise AttestationNotPossible(
            "attestations are offered for '%s' only. The other feeds' publishers keep dated "
            "back-versions online, so a point-in-time statement about them is reproducible "
            "from the publisher and this archive adds nothing to it." % ATTEST_FEED
        )
    document = attest(
        args.rfc,
        root=root,
        on=args.on,
        between=tuple(args.between) if args.between else None,
    )
    if args.output:
        target = Path(args.output)
        target.parent.mkdir(parents=True, exist_ok=True)
        with open(target, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(document)
        print("wrote %s (%d bytes)" % (target, len(document.encode("utf-8"))))
    else:
        print(document)
    return 0


def cmd_paid_push(args) -> int:
    root = resolve_repo_root(args.root)
    targets = load_targets(args.targets_json)
    report = paid_push(
        args.feed,
        root=root,
        targets=targets,
        dry_run=args.dry_run,
        message=args.message,
    )

    if report["outcome"] == "no-targets":
        print("%s: no paid targets configured - skipping" % args.feed)
    else:
        print(
            "%s: %d target(s), %d file(s) in the slice"
            % (args.feed, report["target_count"], len(report["files"]))
        )
    for line in report.get("tree", []):
        print("  %10d  %s" % (line["bytes"], line["path"]))
    for outcome in report["targets"]:
        # `target` is a hash of the URL, never the URL: this log is public from
        # 2026-09-22 and a subscriber's repository name is not ours to publish.
        print(
            "  %s: %s%s"
            % (
                outcome["target"],
                outcome["outcome"],
                " - %s" % outcome["note"] if outcome.get("note") else "",
            )
        )

    if args.report:
        target = Path(args.report)
        target.parent.mkdir(parents=True, exist_ok=True)
        with open(target, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(json.dumps(report, indent=2, sort_keys=True) + "\n")
        print("wrote %s" % target)

    return 1 if report["outcome"] == "failure" else 0


def cmd_status(args) -> int:
    root = resolve_repo_root(args.root)
    feeds = load_feeds(root / "feeds.yaml")
    rows = []
    for feed in feeds.values():
        state = load_state(feed.id, root)
        versions = list_versions(feed.id, root)
        rows.append(
            (
                feed.id,
                "yes" if feed.enabled else "no",
                str(len(versions)),
                versions[-1] if versions else "-",
                (state.get("last_fetched_at") or "-")[:19],
                state.get("last_result") or "-",
            )
        )
    headers = ("feed", "enabled", "versions", "latest", "last fetched (UTC)", "last result")
    widths = [max(len(headers[i]), *(len(r[i]) for r in rows)) for i in range(len(headers))]
    fmt = "  ".join("%%-%ds" % w for w in widths)
    print(fmt % headers)
    print(fmt % tuple("-" * w for w in widths))
    for row in rows:
        print(fmt % row)
    if args.json:
        print(json.dumps([dict(zip(headers, r)) for r in rows], indent=2))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="govdiff", description=__doc__)
    parser.add_argument("--version", action="version", version="govdiff %s" % __version__)
    # `--repo` is the documented spelling; `--root` is days 1-4's name for the
    # same thing and still works. Both land in args.root.
    parser.add_argument(
        "--repo",
        "--root",
        dest="root",
        metavar="PATH",
        help=(
            "the archive checkout to work in. Default: $GOVDIFF_REPO, or the current"
            " directory when it holds feeds.yaml."
        ),
    )
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="fetch a feed, snapshot it if it changed, diff it")
    run.add_argument("feed", nargs="?", help="feed id; omit to run every enabled feed")
    run.set_defaults(func=cmd_run)

    boot = sub.add_parser("bootstrap", help="load a publisher's whole back catalogue")
    boot.add_argument("feed")
    boot.add_argument("--delay", type=int, default=3, help="seconds between requests (default 3)")
    boot.set_defaults(func=cmd_bootstrap)

    redo = sub.add_parser(
        "rediff", help="rebuild every consecutive diff of a feed from the stored snapshots"
    )
    redo.add_argument("feed")
    redo.set_defaults(func=cmd_rediff)

    idx = sub.add_parser(
        "index",
        help=(
            "write docs/index.json, docs/feed.xml, docs/<feed>/feed.xml,"
            " docs/<feed>/changes.json and CHANGES.md"
        ),
    )
    idx.add_argument("--output", help="write the index somewhere other than docs/index.json")
    idx.add_argument(
        "--no-change-feed",
        action="store_true",
        help="write only docs/index.json, not the Atom feeds, changes.json or CHANGES.md",
    )
    idx.set_defaults(func=cmd_index)

    att = sub.add_parser(
        "attest",
        help="write a point-in-time attestation about one RFC from the archived snapshots",
        description=(
            "Produce a Markdown statement of whether an RFC appeared on the SAT 69-B list "
            "on a given date, or across a span of dates, with the snapshot version ids, "
            "their sha256, the SAT document URL and the Last-Modified value at the time. "
            "Reads the local archive only; makes no network request."
        ),
    )
    att.add_argument("feed", help="the feed to attest; only '%s' is offered" % ATTEST_FEED)
    att.add_argument("--rfc", required=True, help="the taxpayer id to look for")
    when = att.add_mutually_exclusive_group(required=True)
    when.add_argument("--on", metavar="YYYY-MM-DD", help="the single date to attest")
    when.add_argument(
        "--between",
        nargs=2,
        metavar=("FROM", "TO"),
        help="two dates; the statement covers every list observed across the span",
    )
    att.add_argument("--output", metavar="PATH", help="write to a file instead of stdout")
    att.set_defaults(func=cmd_attest)

    paid = sub.add_parser(
        "paid-push",
        help="push one feed's slice to the private repositories configured for it",
        description=(
            "Copy one feed's data, diffs, state, Atom feed and changes.json into every "
            "paid target configured for it, and commit and push. Targets come from a "
            "JSON array of {feed, repo, deploy_key_b64} objects - a file, or the "
            "%s environment variable. No targets is a success, not a failure: it is "
            "what an unsold feed looks like. Nothing in the output names a target "
            "repository." % TARGETS_ENV
        ),
    )
    paid.add_argument("--feed", required=True, help="the feed to push")
    paid.add_argument(
        "--targets-json",
        metavar="FILE|env",
        default="env",
        help=(
            "a JSON file holding the targets array, or 'env' to read $%s"
            " (the default), or 'env:NAME' for a different variable" % TARGETS_ENV
        ),
    )
    paid.add_argument(
        "--dry-run",
        action="store_true",
        help="stage the slice into a temporary directory and print it; push nothing",
    )
    paid.add_argument("--message", help="the commit message to use in each target")
    paid.add_argument(
        "--report", metavar="PATH", help="also write the outcome as JSON to this file"
    )
    paid.set_defaults(func=cmd_paid_push)

    status = sub.add_parser("status", help="one line per feed")
    status.add_argument("--json", action="store_true", help="also print the table as JSON")
    status.set_defaults(func=cmd_status)

    # `govdiff --repo PATH status` is the documented order, and it is what the
    # no-archive error message prints, but `govdiff status --repo PATH` is what
    # people type. Accept it after the subcommand as well. SUPPRESS as the
    # default stops the subparser overwriting the value the top-level option
    # already put in the namespace when the option is not repeated here.
    for subparser in sub.choices.values():
        subparser.add_argument(
            "--repo",
            "--root",
            dest="root",
            metavar="PATH",
            default=argparse.SUPPRESS,
            help="the archive checkout to work in; same as the option before the command",
        )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except SourceChallenged as exc:
        # Loud on purpose: the nightly job must fail so the owner is emailed.
        print("SOURCE CHALLENGED: %s" % exc, file=sys.stderr)
        print("The run stopped. No bypass is attempted by design.", file=sys.stderr)
        return 3
    except GovDiffError as exc:
        print("error: %s" % exc, file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
