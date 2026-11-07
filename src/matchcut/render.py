"""Render the one self-contained HTML file.

Constraints the templates have to keep, from the spec:
  - No external requests. CSS and SVG are inlined; no fonts, no scripts, no
    images fetched at view time.
  - Plain grayscale, light and dark through CSS color tokens only.
  - Every chart is inline SVG *and* has a table version beside it.
  - Every section states the number of films it is based on.
  - The report carries data and short sample-size labels. Methodology lives in
    the README, never in the report.

Section order is fixed by `SECTIONS`; the end-to-end test asserts each id is
present in the output.
"""

from __future__ import annotations

from pathlib import Path

from .models import Group, Thresholds

#: Section ids in report order. The end-to-end test checks all of these.
SECTIONS: tuple[str, ...] = (
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


def build_report(
    group: Group,
    thresholds: Thresholds,
    missing_enrichment: int,
    out_path: Path,
) -> None:
    """Compute every section and write the HTML file.

    `missing_enrichment` above zero makes the report declare itself partial and
    drop those films from the genre, decade and language sections only.
    """
    raise NotImplementedError


def bar_chart_svg(values: dict[str, float], width: int = 480) -> str:
    """Inline SVG bar chart using the report's color tokens."""
    raise NotImplementedError


def heatmap_svg(matrix: dict[tuple[str, str], float | None]) -> str:
    """Inline SVG correlation matrix."""
    raise NotImplementedError
