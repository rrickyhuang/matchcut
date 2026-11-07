# matchcut

Take 2 to 6 friends' Letterboxd exports and write one HTML report on how their
film tastes compare.

Nothing is hosted and nothing is uploaded. `matchcut` runs on your machine,
reads export zips you already have, fetches public film pages for genre and
language, and writes a single self-contained HTML file.

> **Status: in development.** The command line, package layout and metric
> definitions below are settled; the computation is still being built.

## Install

Python 3.11 or newer.

```bash
python -m pip install -e ".[dev]"
```

## Use

Put one export zip per person in a folder. The file name without `.zip` becomes
that person's label in the report:

```
exports/
  john.zip
  amy.zip
  sara.zip
```

Then build:

```bash
matchcut build ./exports -o report.html
```

| Option | Meaning |
|---|---|
| `-o`, `--output` | Where to write the report. Default `report.html` |
| `--min-overlap N` | Shared rated films a pair needs before its score stops being flagged "low sample". Default 30 |
| `--min-group N` | Rated films a genre or decade needs before its average is shown. Default 8 |
| `--people a,b,c` | Limit the report to these labels |
| `--cache PATH` | Film enrichment cache. Default `cache/films.json` |
| `--refresh-cache` | Re-fetch film pages instead of using the cache |

## Getting a Letterboxd export

Each person does this once, on their own account:

1. Letterboxd → **Settings** → **Data** → **Export your data**.
2. Drop the .zip file in `exports/` named after them.

`matchcut` reads three files from the zip:

- `ratings.csv` — the ratings every similarity number is built on
- `watched.csv` — the watched library, used for overlap and share breakdowns
- `watchlist.csv` — optional; only the group watchlist recommendations use it

Films are matched on the `boxd.it` short link in the export, never on title, so
re-releases and alternate titles do not split into two films. Someone without a
`watchlist.csv` is simply left out of the watchlist list.

## Enrichment

A Letterboxd export carries no genre or language. For each unique film across
everyone, `matchcut` follows its `boxd.it` link, reads the genres, primary
language and TMDB id off the public film page, and caches the result in
`cache/films.json`.

- One request per second, and never a re-fetch of a film already cached.
- An interrupted run resumes from the cache.
- If Letterboxd starts refusing requests, the run stops and builds a **partial
  report**, which says how many films lack genre and language data and leaves
  them out of those sections only.

No profile pages are fetched, and no private notes, diary entries or review
text are read.

## Metrics

Throughout, a **shared film** means a film two people both *rated*. Unrated
watched films never affect similarity; they count only toward library overlap
and the share breakdowns. Ratings run 0.5 to 5 in half-star steps.

| Metric | Definition |
|---|---|
| Similarity | Pearson correlation of ratings on shared films, always shown with the shared-film count |
| Closeness | Mean absolute rating difference on shared films, and the share within 0.5 stars |
| Library overlap | Films both watched ÷ films either watched |
| Tilt | A person's mean rating minus the others' mean, over films they share with at least one other |
| Rating distribution | Share of a person's ratings at each half-star |
| Group agreement | Rating spread (highest − lowest) per film among members who rated it. Uses films every member rated; if fewer than 20 qualify, falls back to films at least 3 members rated (every member, for a pair), and says so |
| Hot takes | Films the person and at least 2 others rated, ranked by the gap between their rating and the others' mean. Top 4 above, top 4 below |
| Calling cards | The person's 5-star films no other member has watched. Up to 6, most recently logged first |
| Genre share | Share of a person's watched films tagged with each genre. A film can carry several genres, so these do not sum to 100% |
| Genre average | Mean rating in a genre, shown only at 8 or more rated films |
| Decade share and average | The same, by release decade |
| Language share | Share of watched films by **primary** language only, shown as English, other, and the top 5 other languages |

### Sample sizes

A number with too little behind it is misleading, so:

- A pair under `--min-overlap` (default 30) shared ratings still gets a score,
  but it is flagged **low sample** rather than hidden.
- A genre or decade average under `--min-group` (default 8) rated films is
  withheld instead of shown.
- Every section states how many films it is based on.

### Recommendations

**From friends' ratings**, per person: a film they have not watched that at
least 2 other members rated, with a mean of 4.5 or higher. Ranked by mean
rating, then by number of raters. Top 10 each.

**From watchlists**, for the group: a film on at least 2 members' watchlists
that no member has watched. Ranked by how many watchlists it is on. Top 15.

## The report

One HTML file that makes no external requests when you open it. Plain grayscale, with light and dark handled
by CSS color tokens. Every chart is inline SVG and has a table version beside
it. All wording is generated from fixed templates and thresholds, so the same
exports always produce the same sentences.

Sections, in order: summary · at a glance · who rates alike · how each person
uses the stars · what everyone agrees on · hot takes · genres · eras and
languages · calling cards · watch next.

## Development

```bash
python -m pytest
```

```bash
python -m pytest tests/test_cli.py::test_people_option_splits_on_commas
```

Metrics are pure functions over made-up fixture exports with hand-computed
answers. Film-page parsing is tested against a saved page in
`tests/fixtures/`, never against the live site.

## Prior art

`matchcut` is not affiliated with Letterboxd.