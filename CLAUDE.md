# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A Claude Code **plugin** (not an app). The product is mostly the `SKILL.md` prompts in `skills/*/`; the
Python scripts are helpers those skills call via `$CLAUDE_PLUGIN_ROOT/skills/...`. There are three skills:
`init` (welcome page and backend readiness), `plan-trip` (four gated phases, then a PDF), and `travel-profile`
(per-user preference profiles).

## Commands

There is no build step, no linter config and no test suite. Python 3.12 (see `.devcontainer/`).

```bash
pip install -r requirements.txt                       # reportlab, geopandas, shapely, ... (pymupdf is optional, for page rasterising)
git config core.hooksPath hooks                       # install the profile-leak pre-commit guard (do this once)

python3 skills/init/status.py                         # readiness check; prints a STATUS_JSON=... line
python3 skills/plan-trip/fetch_data.py [--check]      # download (or just report) the Natural Earth map data, ~70 MB
python3 skills/plan-trip/schema/validate.py [trip.json]   # schema + cross-checks; defaults to pnw_example.json
python3 skills/plan-trip/build_itinerary.py skills/plan-trip/schema/pnw_example.json [--out output/X.pdf]
python3 skills/travel-profile/profiles.py where       # also: list/show/save/delete/get-active-profile/export/import/migrate/dir
python3 skills/travel-profile/profile_sync.py status  # also: setup <url> / pull / push
```

To smoke-test a change to the engine or the schema, validate and build both examples
(`schema/pnw_example.json` and `schema/yellowstone_example.json`), then rasterise the PDF pages and check
for overflow. The planner skill requires that check before it delivers a PDF.

## Architecture

**Itinerary pipeline (`skills/plan-trip/`).** `schema/itinerary.schema.json` is the contract between the
conversation and the renderer. The JSON holds clean content only. `build_itinerary.py` (ReportLab plus a
matplotlib/geopandas map) owns all presentation: fonts, icons, uppercasing, map label de-confliction,
KeepTogether, one page per section. Never put formatting hacks in the data. `schema/validate.py` runs
cross-checks the schema can't express. A restaurant scheduled on a day it is closed (`dining[].closed`
against `days[].date`/`weekday`) is an error. The rest are warnings: a day's restaurant missing from
the shortlist, one cuisine taking over the dinners, an entry with no `why`/`dishes`. When the schema
changes, update the schema, the validator, the engine, both example JSONs and the "Assembling the schema"
section of `plan-trip/SKILL.md` together. `STYLE.md` is the design and content quality bar.

**Data locations.** Nothing per-user lives in the repo. Map shapefiles go to `$CLAUDE_PLUGIN_DATA`
(fallback `$TRAVEL_ITINERARY_DATA`, then `~/.claude/plugins/data/travel-itinerary/`). `fetch_data.py` tries
the Natural Earth CDN first, then falls back to Natural Earth's GitHub repo, which has a different fetch
strategy (loose sidecar files instead of a zip). The fonts and Tabler icons in `assets/` are bundled.
`build_itinerary.py` looks icons up by category and falls back to a neutral icon.

**Profiles (`skills/travel-profile/`).** A profile is one markdown file: YAML frontmatter for the
machine-checked fields (`diet`, `budget`, `mobility`, `settings.research_depth`), then prose.
`profile_store.py` is the single definition of the format and of the resolution order:
`$TRAVEL_PROFILE_PATH`, then the private repo clone (`$TRAVEL_PROFILE_REPO`), then `~/.claude/travel/profiles`,
then legacy JSON (read-only, converted on read). Both `profiles.py` and `init/status.py` import it.
The CLI reports two failure states, and the skills handle them differently: `PROFILE_STORE_MISSING`
(likely lost with an ephemeral container) and `NO_ACTIVE_PROFILE` (the user is new). `profile_sync.py`
syncs with a private git repo (a shallow, blobless clone sparse to `profiles/`) and refuses a public repo.

**Stdlib-only constraint.** `status.py`, `profile_store.py`, `profile_sync.py`, `profiles.py` and
`fetch_data.py` run before dependencies are installed, so they must not import third-party packages.
That is why `profile_store.py` has its own small YAML-subset parser: top-level plus one nesting level,
`>`/`|` block scalars and simple scalars. Don't add PyYAML as a requirement.

## Rules specific to this repo

- **Never commit a traveller profile.** The repo is public and distributed through a marketplace.
  `hooks/pre-commit` blocks a staged file whose frontmatter has `schema_version:` and `diet:`, and a JSON
  file with both `fixed_preferences` and `dietary_restrictions`. Keep documentation examples inside fenced
  code blocks so the hook doesn't fire on them.
- **Version bumps:** update `version` in both `.claude-plugin/plugin.json` and `.claude-plugin/marketplace.json`.
- Skill invocation strings like `/travel-itinerary:plan-trip` appear in the SKILL.md files and the README.
  Keep them exact.
- The output must contain no images except the generated Natural Earth map: no photos, no stock art.
