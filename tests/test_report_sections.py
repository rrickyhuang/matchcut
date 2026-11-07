"""The report's section list, in order: the contract `test_report.py` checks."""

from matchcut.render import SECTIONS


def test_sections_are_in_spec_order():
    assert SECTIONS == (
        "summary",
        "at-a-glance",
        "who-rates-alike",
        "star-usage",
        "agreement",
        "hot-takes",
        "genres",
        "eras-and-languages",
        "calling-cards",
        "watch-next",
    )
