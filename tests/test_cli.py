"""The CLI parser is real code already, so it is testable at scaffold time."""

import pytest

from matchcut.cli import build_parser
from matchcut.models import Thresholds


def test_build_defaults_match_the_spec():
    args = build_parser().parse_args(["build", "./exports"])
    assert args.exports.name == "exports"
    assert args.output.name == "report.html"
    assert args.min_overlap == Thresholds.min_overlap == 30
    assert args.min_group == Thresholds.min_group == 8
    assert args.people is None
    assert args.refresh_cache is False


def test_people_option_splits_on_commas():
    args = build_parser().parse_args(
        ["build", "./exports", "--people", "ricky, amber ,lenclipse"]
    )
    assert args.people == ["ricky", "amber", "lenclipse"]


def test_build_requires_an_exports_folder():
    with pytest.raises(SystemExit):
        build_parser().parse_args(["build"])
