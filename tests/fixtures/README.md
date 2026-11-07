# Fixtures

- `exports/*.zip` — small made-up exports with hand-computed expected answers.
  Keep them tiny enough that every metric's correct value can be worked out by
  hand and written into the test.
- `film_page.html` — one saved Letterboxd film page. `enrich.parse_film_page`
  is tested only against this, never against the live site.

Nothing here is real user data.
