# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
python -m pip install -e ".[dev]"   # editable install; also puts `matchcut` on PATH
python -m pytest                    # full suite
python -m pytest tests/test_cli.py::test_people_option_splits_on_commas   # one test
matchcut build ./exports -o report.html
```

There is no linter or formatter configured. Don't add one without asking.

## What this is

A local Python tool: read 2 to 6 Letterboxd export zips, fetch genre and
language off public film pages, compute taste-comparison metrics, write one
self-contained HTML report. No server, no accounts, no AI text at run time.

`matchcut-spec.md` in the repo root is the authoritative design doc — metric
definitions, thresholds, report section order, milestones and the acceptance
test. It is **deliberately untracked** (`.gitignore`) because it names real
people. Read it before changing behaviour; the README is the public subset.

## Pipeline

One direction, no cycles. `cli.cmd_build` wires it up:

```
exports.load_people   zips      -> list[Person]
enrich.enrich         boxd ids  -> dict[boxd_id, FilmInfo] + missing count
                                   (cached in cache/films.json)
Group(people, films)
metrics.* / recommend.*          -> plain dicts and dataclasses
render.build_report              -> one HTML file
```

`models.py` holds the types every stage shares and is the place to look first.
It is not in the spec's layout — it was added so the stages have one contract
instead of passing loose dicts.

### Invariants worth not breaking

- **Films are keyed by `boxd.it` short id everywhere.** Never match on title or
  title+year. The export gives the short link; use it.
- **"Shared film" always means both people *rated* it.** Unrated watched films
  affect library overlap and the share breakdowns only, never similarity.
- **Enrichment is optional data.** A film with `FilmInfo.status != "ok"` is
  excluded from the genre, decade and language sections and counted toward the
  partial-report notice — it is never dropped from similarity or ratings.
  `Group.enriched()` enforces this; use it rather than `Group.films[...]`.
- **Metrics are pure.** No fetching, no file access, no number formatting in
  `metrics.py` or `recommend.py`. That is what makes them testable by hand.
- **Report wording is deterministic.** Summary facts come from fixed templates
  that fire on thresholds. Same exports must always give the same sentences.
  No randomness, no model calls.
- **Low samples are flagged, not hidden** — except genre/decade averages under
  `--min-group`, which are withheld. Both floors live in `Thresholds`.

## Page parsing is the fragile part

`enrich.parse_film_page` is the only function that knows the structure of a
Letterboxd film page. Keep it that way, and keep it tested against the saved
page in `tests/fixtures/`, never against the live site.

Fetching rules are not negotiable: one request per second, browser-like user
agent, exponential backoff, resume from cache, and stop after 5 consecutive
403/429 responses to build a partial report instead. Only film pages are
fetched — never profile pages.

**Open risk:** it is not yet confirmed that a script can fetch film pages at
all. A plain fetch tool was blocked as a bot where a real browser session was
not. Milestone 1 settles this before anything is built on top of it.

## Report constraints

`render.py` writes one file that makes zero external requests at view time —
no fonts, no scripts, no remote images. Grayscale only, light and dark through
the CSS tokens in `templates/base.html` and nothing else. Every chart is inline
SVG *and* has a table version. Every section states how many films it is based
on. Methodology belongs in the README, not in the report. `render.SECTIONS`
fixes the order and is what the end-to-end test asserts against.

## Data handling

The repo is public and the data is other people's.

- `exports/`, `cache/` and root `*.html` are gitignored. Never commit a real
  export, a cache built from one, or a generated report.
- `.gitignore` is allowlist style (`*` first, then explicit `!` lines). Adding a
  tracked file means adding a `!` line, not restructuring it.
- Fixtures are made up. Don't build fixtures by trimming a real export.
