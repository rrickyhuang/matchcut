"""The correlation matrix takes its colours from the CSS tokens, in both themes."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from matchcut.render import HEAT_STEPS, TEMPLATE_DIR, heat_step, heatmap_svg

from .conftest import make_pair


@pytest.mark.parametrize(
    "score,step",
    [(-1.0, 0), (-0.8, 0), (-0.4, 1), (0.0, 2), (0.4, 3), (0.8, 4), (1.0, 4)],
)
def test_correlation_maps_to_a_step(score, step):
    assert heat_step(score) == step


def test_cells_use_tokens_and_no_literal_colours():
    svg = heatmap_svg(["ana", "ben"], [make_pair(0.9)])
    assert "rgb(" not in svg and "#" not in svg.replace("&#8212;", "")
    assert 'fill="var(--heat-4)"' in svg
    assert 'fill="var(--heat-4-text)"' in svg


def test_a_low_correlation_uses_the_lightest_step():
    svg = heatmap_svg(["ana", "ben"], [make_pair(-0.9)])
    assert 'fill="var(--heat-0)"' in svg
    assert 'fill="var(--heat-0-text)"' in svg


# --------------------------------------------------------------------------
# contrast, read from the stylesheet itself
# --------------------------------------------------------------------------


def _luminance(hex_colour: str) -> float:
    def channel(index: int) -> float:
        value = int(hex_colour[index : index + 2], 16) / 255
        return value / 12.92 if value <= 0.03928 else ((value + 0.055) / 1.055) ** 2.4

    return 0.2126 * channel(1) + 0.7152 * channel(3) + 0.0722 * channel(5)


def _contrast(a: str, b: str) -> float:
    high, low = sorted((_luminance(a), _luminance(b)), reverse=True)
    return (high + 0.05) / (low + 0.05)


def _themes() -> list[dict[str, str]]:
    """Token values for each theme block in base.html, in file order.

    Every block starts with `--bg`, so that is where a new theme begins:
    light, dark by media query, dark by `data-theme`.
    """
    css = (Path(TEMPLATE_DIR) / "base.html").read_text(encoding="utf-8")
    themes: list[dict[str, str]] = []
    for name, value in re.findall(r"(--[\w-]+):\s*(#[0-9a-fA-F]{6})", css):
        if name == "--bg":
            themes.append({})
        themes[-1][name] = value.lower()
    return themes


def test_there_are_three_theme_blocks():
    assert len(_themes()) == 3


@pytest.mark.parametrize("theme", range(3))
@pytest.mark.parametrize("step", range(HEAT_STEPS))
def test_every_step_keeps_its_label_readable(theme, step):
    tokens = _themes()[theme]
    ratio = _contrast(tokens[f"--heat-{step}"], tokens[f"--heat-{step}-text"])
    assert ratio >= 4.5, f"theme {theme} step {step}: {ratio:.2f}:1"
