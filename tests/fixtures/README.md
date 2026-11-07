# Fixtures

- Export zips are not stored here. `write_export` in `tests/conftest.py` builds
  small made-up ones in a temporary folder for each test (`ANA_RATINGS`,
  `BEN_RATINGS` and `CLEO_RATINGS` hold the ratings). Keep them tiny enough that
  every metric's correct value can be worked out by hand and written into the
  test.
- `film_page.html` — one saved Letterboxd film page. `enrich.parse_film_page`
  is tested only against this, never against the live site.

Nothing here is real user data.
