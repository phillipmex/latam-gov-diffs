"""Command line entry point: `govdiff run|bootstrap|status`."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from govdiff import __version__
from govdiff.config import load_feeds, repo_root
from govdiff.errors import GovDiffError, SourceChallenged
from govdiff.fetch import load_state
from govdiff.runner import bootstrap_cclasstrib, run_all, run_feed
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
    root = Path(args.root).resolve() if args.root else repo_root()
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
    root = Path(args.root).resolve() if args.root else repo_root()
    if args.feed != "cclasstrib":
        print("bootstrap is only implemented for cclasstrib", file=sys.stderr)
        return 2
    report = bootstrap_cclasstrib(root, delay=args.delay)
    print("listing shows %d cClassTrib release(s)" % report["listed"])
    if report.get("note"):
        print(report["note"])
        return 0
    for version in report["versions"]:
        print(
            "  %s  %s  %5d rows  %7d bytes  %s"
            % (
                version["published"],
                version["version_id"],
                version["rows"],
                version["bytes"],
                "new" if version["created"] else "already stored",
            )
        )
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


def cmd_status(args) -> int:
    root = Path(args.root).resolve() if args.root else repo_root()
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
    parser.add_argument("--root", help="repository root (default: the installed package's repo)")
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="fetch a feed, snapshot it if it changed, diff it")
    run.add_argument("feed", nargs="?", help="feed id; omit to run every enabled feed")
    run.set_defaults(func=cmd_run)

    boot = sub.add_parser("bootstrap", help="load a publisher's whole back catalogue")
    boot.add_argument("feed")
    boot.add_argument("--delay", type=int, default=3, help="seconds between requests (default 3)")
    boot.set_defaults(func=cmd_bootstrap)

    status = sub.add_parser("status", help="one line per feed")
    status.add_argument("--json", action="store_true", help="also print the table as JSON")
    status.set_defaults(func=cmd_status)
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
