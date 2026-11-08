"""Render the one self-contained HTML file.

Constraints the templates have to keep:
  - No external requests. CSS and SVG are inlined; no fonts, no scripts, no
    images fetched at view time.
  - Plain grayscale, light and dark through the CSS tokens in `base.html`.
  - Every chart is inline SVG *and* has a table version beside it.
  - Every section states the number of films it is based on.
  - The report carries data and short sample-size labels. Methodology lives in
    the README, never in the report.

Section order is fixed by `SECTIONS`; the end-to-end test asserts each id is
present in the output.

Charts are built here rather than in the template because an SVG assembled by
string concatenation in Jinja is unreadable. They use the same CSS custom
properties as the rest of the page, so they theme for free.
"""

from __future__ import annotations

import html
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from . import __version__
from .metrics import (
    PairStats,
    calling_cards,
    consensus,
    decade_breakdown,
    genre_breakdown,
    group_agreement,
    hot_takes,
    language_breakdown,
    pair_stats,
    person_stats,
    summary_facts,
)
from .models import RATING_STEPS, Group, Thresholds
from .recommend import from_friends_ratings, from_watchlists

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

TEMPLATE_DIR = Path(__file__).parent / "templates"


def build_report(
    group: Group,
    thresholds: Thresholds,
    missing_enrichment: int,
    out_path: Path,
) -> None:
    """Compute every section and write the HTML file.

    `missing_enrichment` above zero makes the report declare itself partial and
    drop those films from the genre and language sections only.
    """
    pairs = pair_stats(group, thresholds)
    people = person_stats(group)
    genres = genre_breakdown(group, thresholds)
    decades = decade_breakdown(group, thresholds)
    languages = language_breakdown(group, thresholds)

    env = Environment(
        loader=FileSystemLoader(TEMPLATE_DIR),
        autoescape=select_autoescape(["html"]),
        trim_blocks=True,
        lstrip_blocks=True,
    )
    env.filters["stars"] = _stars
    env.filters["pct"] = _pct
    env.filters["signed"] = _signed

    template = env.get_template("report.html")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        template.render(
            title=_report_title(group),
            version=__version__,
            labels=group.labels,
            thresholds=thresholds,
            missing_enrichment=missing_enrichment,
            total_films=len(group.films),
            facts=summary_facts(group, thresholds),
            people=people,
            pairs=pairs,
            matrix_svg=heatmap_svg(group.labels, pairs),
            rating_steps=RATING_STEPS,
            distribution_svg={
                p.label: bar_chart_svg(
                    {f"{step:g}": p.distribution[step] for step in RATING_STEPS}
                )
                for p in people
            },
            agreement=group_agreement(group),
            consensus=consensus(group),
            takes=hot_takes(group),
            genres=genres,
            genre_svg=_share_charts(genres, limit=8),
            decades=decades,
            decade_svg=_share_charts(decades, limit=12),
            languages=languages,
            cards=calling_cards(group),
            friend_picks=from_friends_ratings(group),
            watchlist_picks=from_watchlists(group),
            no_watchlist=[p.label for p in group.people if not p.has_watchlist],
        ),
        encoding="utf-8",
    )


def _report_title(group: Group) -> str:
    labels = group.labels
    if len(labels) == 2:
        return f"{labels[0]} and {labels[1]}"
    return ", ".join(labels[:-1]) + f" and {labels[-1]}"


# --------------------------------------------------------------------------
# Formatting filters
# --------------------------------------------------------------------------


def _stars(value: float | None, places: int = 2) -> str:
    """A rating or a star difference. Em dash when there is no number."""
    return "—" if value is None else f"{value:.{places}f}"


def _pct(value: float | None, places: int = 0) -> str:
    return "—" if value is None else f"{value * 100:.{places}f}%"


def _signed(value: float | None, places: int = 2) -> str:
    return "—" if value is None else f"{value:+.{places}f}"


# --------------------------------------------------------------------------
# Charts. Inline SVG, themed by the same CSS tokens as the page.
# --------------------------------------------------------------------------

_BAR_HEIGHT = 18
_BAR_GAP = 6
_LABEL_WIDTH = 108
_VALUE_WIDTH = 52


def bar_chart_svg(
    values: dict[str, float],
    width: int = 460,
    as_percent: bool = True,
) -> str:
    """Horizontal bars, longest bar scaled to the full track.

    Every label is escaped here, since the template marks the result safe.
    """
    if not values:
        return ""

    rows = list(values.items())
    track = max(width - _LABEL_WIDTH - _VALUE_WIDTH, 40)
    biggest = max(values.values()) or 1.0
    height = len(rows) * (_BAR_HEIGHT + _BAR_GAP)

    parts = [
        f'<svg viewBox="0 0 {width} {height}" width="{width}" height="{height}" '
        f'role="img" aria-label="bar chart">'
    ]
    for index, (key, value) in enumerate(rows):
        y = index * (_BAR_HEIGHT + _BAR_GAP)
        text_y = y + _BAR_HEIGHT * 0.75
        bar = max(round(track * (value / biggest)), 1 if value > 0 else 0)
        shown = f"{value * 100:.0f}%" if as_percent else f"{value:g}"
        parts.append(
            f'<text x="0" y="{text_y:.0f}" font-size="12" fill="var(--muted)">'
            f"{html.escape(str(key))}</text>"
            f'<rect x="{_LABEL_WIDTH}" y="{y}" width="{track}" '
            f'height="{_BAR_HEIGHT}" fill="var(--surface)" rx="2"/>'
            f'<rect x="{_LABEL_WIDTH}" y="{y}" width="{bar}" '
            f'height="{_BAR_HEIGHT}" fill="var(--mark)" rx="2"/>'
            f'<text x="{_LABEL_WIDTH + track + 8}" y="{text_y:.0f}" font-size="12" '
            f'fill="var(--muted)">{shown}</text>'
        )
    parts.append("</svg>")
    return "".join(parts)


_CELL = 64
HEAT_STEPS = 5


def heat_step(score: float) -> int:
    """Which `--heat-N` token a correlation uses: -1..1 onto 0..4, in even
    bands (-1 to -0.6 is 0, 0.6 to 1 is 4)."""
    strength = max(0.0, min(1.0, (score + 1) / 2))
    return min(int(strength * HEAT_STEPS), HEAT_STEPS - 1)


def heatmap_svg(labels: list[str], pairs: list[PairStats]) -> str:
    """The correlation matrix. More ink means more alike.

    Cell and label colours are the `--heat-N` tokens in `base.html`, so both
    themes keep the label readable. Nothing here is a literal colour.

    A pair with no score is left blank rather than shaded, so the picture never
    implies a number the table withholds. A low-sample score is marked `*`.
    """
    if len(labels) < 2:
        return ""

    scores: dict[tuple[str, str], PairStats] = {}
    for pair in pairs:
        scores[(pair.a, pair.b)] = pair
        scores[(pair.b, pair.a)] = pair

    left = max((len(label) for label in labels), default=0) * 7 + 12
    top = 22
    size = _CELL * len(labels)
    width = left + size
    height = top + size

    parts = [
        f'<svg viewBox="0 0 {width} {height}" width="{width}" height="{height}" '
        f'role="img" aria-label="correlation matrix">'
    ]
    for col, label in enumerate(labels):
        x = left + col * _CELL + _CELL / 2
        parts.append(
            f'<text x="{x:.0f}" y="14" font-size="11" text-anchor="middle" '
            f'fill="var(--muted)">{html.escape(label)}</text>'
        )
    for row, row_label in enumerate(labels):
        y = top + row * _CELL
        parts.append(
            f'<text x="{left - 8}" y="{y + _CELL / 2 + 4:.0f}" font-size="11" '
            f'text-anchor="end" fill="var(--muted)">{html.escape(row_label)}</text>'
        )
        for col, col_label in enumerate(labels):
            x = left + col * _CELL
            if row == col:
                parts.append(
                    f'<rect x="{x}" y="{y}" width="{_CELL}" height="{_CELL}" '
                    f'fill="var(--surface)" stroke="var(--bg)" stroke-width="2"/>'
                )
                continue
            pair = scores.get((row_label, col_label))
            score = pair.correlation if pair else None
            if score is None:
                parts.append(
                    f'<rect x="{x}" y="{y}" width="{_CELL}" height="{_CELL}" '
                    f'fill="var(--surface)" stroke="var(--bg)" stroke-width="2"/>'
                    f'<text x="{x + _CELL / 2:.0f}" y="{y + _CELL / 2 + 4:.0f}" '
                    f'font-size="12" text-anchor="middle" fill="var(--muted)">'
                    f"&#8212;</text>"
                )
                continue
            step = heat_step(score)
            flag = "*" if pair.low_sample else ""
            parts.append(
                f'<rect x="{x}" y="{y}" width="{_CELL}" height="{_CELL}" '
                f'fill="var(--heat-{step})" stroke="var(--bg)" '
                f'stroke-width="2"/>'
                f'<text x="{x + _CELL / 2:.0f}" y="{y + _CELL / 2 + 4:.0f}" '
                f'font-size="12" text-anchor="middle" '
                f'fill="var(--heat-{step}-text)">{score:.2f}{flag}</text>'
            )
    parts.append("</svg>")
    return "".join(parts)


def _share_charts(breakdown, limit: int) -> dict[str, str]:
    """One share chart per person, trimmed to the biggest `limit` keys."""
    return {
        label: bar_chart_svg({row.key: row.share for row in rows[:limit]})
        for label, rows in breakdown.per_person.items()
    }
