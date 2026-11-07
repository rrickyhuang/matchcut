"""Command line entry point: `matchcut build ./exports -o report.html`."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import __version__
from .models import Thresholds


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="matchcut",
        description="Compare friends' Letterboxd exports and write one HTML report.",
    )
    parser.add_argument("--version", action="version", version=f"matchcut {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    build = sub.add_parser("build", help="build the HTML report")
    build.add_argument(
        "exports",
        type=Path,
        help="folder holding one Letterboxd export zip per person",
    )
    build.add_argument(
        "-o",
        "--output",
        type=Path,
        default=Path("report.html"),
        help="where to write the report (default: report.html)",
    )
    build.add_argument(
        "--min-overlap",
        type=int,
        default=Thresholds.min_overlap,
        metavar="N",
        help="minimum shared rated films before a pair score is flagged "
        f"low sample (default: {Thresholds.min_overlap})",
    )
    build.add_argument(
        "--min-group",
        type=int,
        default=Thresholds.min_group,
        metavar="N",
        help="minimum rated films for a genre or decade average "
        f"(default: {Thresholds.min_group})",
    )
    build.add_argument(
        "--people",
        type=lambda s: [part.strip() for part in s.split(",") if part.strip()],
        default=None,
        metavar="a,b,c",
        help="limit the report to these labels",
    )
    build.add_argument(
        "--cache",
        type=Path,
        default=Path("cache/films.json"),
        help="film enrichment cache (default: cache/films.json)",
    )
    build.add_argument(
        "--refresh-cache",
        action="store_true",
        help="re-fetch film pages instead of using the cache",
    )
    build.set_defaults(func=cmd_build)
    return parser


def cmd_build(args: argparse.Namespace) -> int:
    from .enrich import enrich
    from .exports import load_people
    from .models import Group
    from .render import build_report

    thresholds = Thresholds(min_overlap=args.min_overlap, min_group=args.min_group)

    people = load_people(args.exports, only=args.people)
    print(f"Loaded {len(people)}: {', '.join(p.label for p in people)}")

    # Only watched films need enrichment. A watchlist pick is listed by title
    # and year, both of which the export already carries.
    refs = {
        boxd_id: ref for person in people for boxd_id, ref in person.watched.items()
    }
    films, missing = enrich(
        refs, args.cache, refresh=args.refresh_cache, progress=print
    )

    group = Group(people=people, films=films)
    build_report(group, thresholds, missing, args.output)

    print(f"Wrote {args.output} for {len(people)} people over {len(refs)} films.")
    if missing:
        print(f"Partial report: {missing} films lack genre and language data.")
    return 0


def main(argv: list[str] | None = None) -> int:
    from .exports import ExportError

    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except ExportError as exc:
        print(f"matchcut: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print(
            "\nmatchcut: stopped. Films already fetched stay cached, so the "
            "next run resumes.",
            file=sys.stderr,
        )
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
