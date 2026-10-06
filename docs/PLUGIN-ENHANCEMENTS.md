# travel-itinerary — implementation brief

**Written:** 2026-10-06 · **For:** a desktop Claude Code session working in this repo
**Status:** design agreed, not yet built

This brief is self-contained. It assumes no knowledge of the conversation that produced
it. Read it top to bottom, then work the **Order of work** section at the end.

---

## 0. What this covers

Three changes, in priority order:

1. **Traveller profiles do not survive a cloud session.** Root cause identified below.
   Fix: move the profile to a markdown file with YAML frontmatter, persisted somewhere
   that outlives the container.
2. **Add a dedicated restaurants page** to the generated PDF — grouped by budget, with
   hours, cuisine, the reason for the recommendation, and highlight dishes.
3. **Make the map-data download survive a restricted network.** Discovered incidentally;
   cheap to fix while in the area.

A fourth section records **layout limits measured empirically** against the PDF engine.
Read it before touching `build_itinerary.py` — it will save a lot of rebuild cycles.

---

## 1. Repo orientation

```
.claude-plugin/     plugin.json, marketplace.json
skills/
  init/             SKILL.md, status.py                 welcome + backend readiness
  plan-trip/        SKILL.md, build_itinerary.py        the PDF engine
                    fetch_data.py                       Natural Earth downloader
                    STYLE.md
                    schema/itinerary.schema.json        the data contract
                    schema/validate.py
                    schema/pnw_example.json             worked example (5-day)
                    schema/yellowstone_example.json     worked example (6-day)
                    assets/fonts, assets/icons
  travel-profile/   SKILL.md, profiles.py, profile.schema.json
requirements.txt, .devcontainer/, LICENSE, README.md
```

**Build command** (run from `skills/plan-trip/`):

```bash
python3 schema/validate.py <trip>.json
python3 build_itinerary.py <trip>.json      # writes output/<name>.pdf
```

`output/` is gitignored.

---

## 2. Problem 1 — profile persistence

### 2.1 Root cause

`skills/travel-profile/profiles.py` resolves storage like this:

```python
def data_root():
    return (os.environ.get("CLAUDE_PLUGIN_DATA")
            or os.environ.get("TRAVEL_ITINERARY_DATA")
            or os.path.expanduser("~/.claude/plugins/data/travel-itinerary"))
```

`skills/plan-trip/build_itinerary.py` and `skills/init/status.py` use the same resolution.

That directory is **outside the repo by design** — the README says profiles "survive plugin
updates and are never in this repo." That reasoning is correct for a laptop install.

**It fails completely in Claude Code on the web.** Each session gets a fresh, ephemeral
container; the repository is cloned in, and nothing else persists. `~/.claude/...` does not
exist on the next run. The profile is written to a directory that is destroyed.

**This is not a bug in the code. It is an assumption that holds for one deployment target
and not the other.**

Observed in a real session: `profiles.py get-active-profile` returned `NO_ACTIVE_PROFILE`
for a user who had onboarded previously, and the 67 MB Natural Earth cache (same directory)
also had to be re-downloaded.

Also confirmed: the repo contains **no** `.claude/settings.json` and **no** hooks, so
nothing restores either artifact.

### 2.2 Secondary defect — the silent empty state

`get-active-profile` exits `NO_ACTIVE_PROFILE` both when the user has genuinely never
onboarded **and** when the storage directory has evaporated. The caller cannot tell the
difference, so a fresh cloud session silently re-interviews a user who already has a
profile, and the previous answers are lost without anyone noticing.

**Fix this even if nothing else on this list gets built.** It is the difference between
losing data and knowing you lost data.

### 2.3 The new format: markdown with YAML frontmatter

Replace the JSON profile with a single markdown file per profile.

Rationale: the planner is driven by a model reading the profile, not by code parsing it.
Prose carries nuance that an enum flattens. Markdown is also hand-editable, diffable, and
pasteable into any chat. Frontmatter keeps the parts that must be machine-checked
checkable. The repo already uses frontmatter-plus-body in every `SKILL.md`, so this is
idiomatic here.

```markdown
---
schema_version: 2
profile_name: default
updated: 2026-10-06
settings:
  research_depth: light          # light | heavy
diet:
  restriction: vegetarian
  strictness: >
    Free text. Capture what is and is not acceptable in the traveller's own terms —
    this is where a rule that is stricter or looser than the label gets recorded.
budget:
  per_meal_cap: 50               # currency-agnostic number
  currency: USD
  tier: mid-range
mobility:
  status: none                   # none | temporary | ongoing
  review_after: null             # date, so a temporary constraint expires
---

# Traveller profile — <name>

## Diet
## Food preferences          <- cuisines, local-speciality appetite, coffee, alcohol
## Photography               <- bodies AND lenses; it changes what is worth recommending
## Activities
## Pace
## Mobility                  <- current constraints, with a review date
## Flights                   <- home airports, loyalty, flexibility
## Lodging format
## Ask per trip              <- group, budget, focus, lodging style
## Trip log                  <- 3 lines per trip: where, when, what worked
```

**Two frontmatter fields deserve special attention**, because both were absent from the old
schema and both caused real planning errors:

- `diet.strictness` — the label ("vegetarian") does not tell you where the traveller
  actually draws the line. Without this field the planner either invents a stricter rule
  than the traveller holds, or a looser one.
- `budget.per_meal_cap` — without a hard number the planner reaches for a headline meal
  that is several times what the traveller intends to spend.

**`mobility.review_after` matters too.** A temporary constraint recorded with no expiry
silently becomes permanent across future trips.

**`## Trip log`** is what makes the profile compound rather than merely persist. It also
stops a future session pitching a destination the traveller has already done.

### 2.4 Where the file lives

Resolution order, first hit wins. **The resolver must report which source it used.**

1. `$TRAVEL_PROFILE_PATH` — explicit override, a file or a directory
2. A cloned private profile repo, if configured
3. `~/.claude/travel/profiles/*.md` — local, and the natural place to point at a synced
   folder (Dropbox / iCloud / OneDrive) for free laptop-to-laptop sync
4. Legacy `~/.claude/plugins/data/travel-itinerary/profiles/*.json` — read-only, for
   migration
5. Nothing found → say so explicitly, list every path checked, and offer `import`

Multiple profiles: one `.md` per profile in the directory, plus an `active` file holding
the active name. Keep the existing `list / show / save / delete / get-active / set-active /
get-active-profile / dir` command surface.

**For cloud sessions, ranked:**

1. **A separate private repo or private gist holding only the profile.** Cloned at session
   start. One-time setup, nothing to remember per session, genuinely shared between cloud
   and desktop. This is the recommended answer.
2. **An environment secret** containing the markdown, written to disk by a SessionStart
   hook. Works; awkward to edit a multi-line document.
3. **Manual upload into the chat.** Keep as a fallback for a one-off machine. Do not make
   it the design — it is a step to forget every session, which is the failure this whole
   change exists to prevent.

### 2.5 PRIVACY — do not store the profile in this repository

This repo is **public** and distributed through a plugin marketplace
(`/plugin marketplace add <owner>/travel-itinerary`). A committed profile publishes
dietary restrictions, home airports, health constraints and travel history.

Required guards:

- `.gitignore` entries for `*.profile.md`, `profiles/`, `.travel-data/`
- **A `pre-commit` hook that hard-fails on a staged file containing profile frontmatter**
  (`schema_version:` plus `diet:` is a sufficient signature). A `.gitignore` entry alone is
  defeated by `git add -f`; the hook is the real guard.
- A line in the README stating plainly that profiles must never be committed here.

### 2.6 Persistence timing — write on change, not at end of session

**There is no reliable end-of-session in Claude Code.** Tabs close, turns are interrupted,
containers are reclaimed. A design that only persists at the end loses exactly the sessions
that ended badly.

- Persist on **every mutation**. If the profile is amended mid-conversation, it is written
  immediately.
- A `Stop` hook may push a final copy, but only as a safety net.
- A `SessionStart` hook restores the profile (and the map cache — see §4) before any skill
  runs.

There is a `session-start-hook` skill available in Claude Code for authoring these; use it
rather than hand-rolling the settings wiring.

### 2.7 Migration

- `profiles.py migrate` converts existing JSON profiles to markdown.
- Keep reading JSON for at least one release; prefer markdown when both exist.
- Add `profiles.py export` and `profiles.py import` (stdin/stdout) so a profile is one
  paste to move between machines regardless of sync setup.

### 2.8 Acceptance criteria

- [ ] A profile created on machine A is readable by a cloud session on machine B with no
      manual step beyond the one-time sync setup.
- [ ] `get-active-profile` on a fresh container with no profile prints every path it
      checked, and is distinguishable from "never onboarded".
- [ ] Amending a profile mid-session persists without waiting for session end.
- [ ] `git add -f` of a profile file is rejected by the pre-commit hook.
- [ ] An existing JSON profile survives `migrate` with no field loss.

---

## 3. Problem 2 — the restaurants page

### 3.1 Why it is worth building

Dining recommendations currently live only in `days[].where_to_eat`, which means **cuisine
is only ever visible one day at a time**. A real itinerary produced by this plugin ended up
with the same cuisine in three of four dinner slots and nothing in the document surfaced it.
A page that lists every recommendation together makes that obvious at a glance.

### 3.2 Schema

Add an optional top-level `dining` object to `schema/itinerary.schema.json`, sibling to
`planning` and `packing`. Optional, so existing trips are unaffected.

```json
"dining": {
  "heading": "Where to Eat",
  "note": "optional one-line intro",
  "groups": [
    {
      "label": "Under $25",
      "entries": [
        {
          "name": "...",                        // required
          "area": "...",                        // required
          "cuisine": "...",                     // required; drives the tally and icon
          "price": "$15–20pp",                  // finer than the group band
          "hours": "Daily 11–9",                // free text, human-readable
          "closed": ["Monday"],                 // STRUCTURED, see below
          "why": "one line — why it earns a slot",
          "dishes": ["...", "..."],
          "booking": "Walk-in | Reserve on X | Cash only",
          "tags": ["late-night", "step-free", "long queue"]
        }
      ]
    }
  ]
}
```

**`closed` must be a structured array, not prose inside `hours`.** It is the single
highest-value field in this schema: it is what lets the validator catch a restaurant
scheduled on a day it is shut. A real itinerary booked a headline dinner on the one night
of the week the restaurant was closed, and nothing caught it.

### 3.3 Renderer

Add `dining_story(itin)` to `build_itinerary.py`, modelled closely on the existing
`planning_story()`. Register it between the planning page and the day pages.

- One section header per budget group, styled like a planning panel label.
- One card per entry: name + area/cuisine line, hours (with a "closed Mon" chip), `why`,
  then dishes.
- **Wrap each entry in `KeepTogether`** so an entry never splits across a page boundary.
- Allow the section to flow to a second page with each group kept whole — the same rule
  the planning page already follows.
- Icons: look up from `cuisine` against `assets/icons/` with the existing neutral fallback.
  `tools-kitchen-2`, `coffee` and `glass-full` already exist.

**Add a cuisine tally line at the top of the page** — `Mexican 4 · Thai 1 · Italian 1 ·
coffee 3`, derived by the engine from `cuisine` across all entries. This is the feature
that makes an imbalance visible.

### 3.4 Keep it a reference page, not a duplicate

`days[].where_to_eat` stays — that is the chosen meal for that day. `dining` is the
shortlist it was drawn from, including alternates and backups. Different jobs.

### 3.5 Validator cross-checks (`schema/validate.py`)

These convert two observed failures into build-time errors:

- **Every `days[].where_to_eat[].place` should resolve to a `dining` entry name.** Warn on
  a miss (do not hard-fail — a day may legitimately name a market stall).
- **Hard-fail if a day schedules an entry whose `closed` array contains that day's
  weekday.** Requires a date or weekday per day; see §3.6.
- **Warn if any single `cuisine` exceeds ~50% of dinner slots.**
- **Warn on an entry with no `dishes` or no `why`** — those are the fields that make the
  page worth printing.

### 3.6 Prerequisite: days need a weekday

The `days[]` entries currently carry `title` and `subtitle` only — no date. The closed-day
check needs one. Add an optional `date` (ISO) or `weekday` field to `days[]`, and have the
validator skip the check when absent rather than failing.

### 3.7 SKILL.md changes (`skills/plan-trip/SKILL.md`)

- Phase 2: collect the dining superset explicitly, not just activities.
- Phase 3 / Gate 3: present the dining page content for approval alongside the outline.
- Add to **Hard rules**: every dining entry carries verified hours, a `closed` array, at
  least one dish, and a reason.
- Add a line to *Content sizing*: see §5 for measured capacity.

Update one of the two bundled examples so the pattern is documented in a working file.

### 3.8 Acceptance criteria

- [ ] A trip JSON with no `dining` block still validates and builds unchanged.
- [ ] The dining page renders grouped by budget with a cuisine tally.
- [ ] No entry splits across a page break.
- [ ] A day scheduling a Monday-closed restaurant on a Monday fails validation.
- [ ] Both bundled examples still build.

---

## 4. Problem 3 — map data on a restricted network

`skills/plan-trip/fetch_data.py` downloads five Natural Earth 10m layers from:

```python
BASE = "https://naciscdn.org/naturalearth/10m"
```

In a sandboxed cloud session this host can be **blocked by egress policy** — observed
failing with `URLError: Tunnel connection failed: 403 Forbidden`, which leaves the engine
unable to render the map at all.

A working fallback is Natural Earth's own GitHub repository, which is the canonical
upstream for the vector data and was reachable where the CDN was not:

```
https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/
    10m_physical/ne_10m_coastline.{shp,shx,dbf,prj,cpg}
    10m_physical/ne_10m_ocean.*
    10m_physical/ne_10m_lakes.*
    10m_physical/ne_10m_rivers_lake_centerlines.*
    10m_cultural/ne_10m_admin_1_states_provinces.*
```

Changes:

- Try each mirror in turn; do not fail the build on the first host.
- On total failure, print the blocked host and the fallback instructions rather than a
  stack trace.
- Have the SessionStart hook pre-fetch, so the first build of a session does not stall on
  a ~67 MB download.

---

## 5. Measured layout limits — read before touching the engine

These were established by building and rasterising, not from the source. They are the
difference between one build and six.

| Constraint | Measured value |
|---|---|
| Planning panels per page | 5 short-row panels fit; the SKILL.md figure of 4 is conservative |
| Day page | ~7 timeline entries with 2–4 line bodies, plus a 3-row eat block and one worth-knowing block. 8 entries overflows |
| `where_to_eat[].category` | **6 characters maximum.** Longer wraps mid-word in the narrow column ("BREAKFAST" renders as "BREAKF / AST"). Safe: DINNER, COFFEE, MARKET, PASTRY, LUNCH, WALK, DRINKS, SPARE |
| `summary.intro` | ~6 rendered lines. Longer pushes the highlights row onto its own near-empty page |
| `summary.highlights` | 6 cards; keep each `name` to one line and each `desc` to two |
| `summary.activity_tags` | ~7 tags = 2 rows. 10 tags = 3 rows and costs a page |
| Map stops | **6 is the practical maximum** at the default 6.6×4.0in figure. 8 stops with 4 inside a 4-mile cluster is illegible |
| Map labels | Stops closer than ~0.05° in latitude need explicit `label_offset`. Leg-label pills become obstacles too — lift a label vertically rather than pushing it far horizontally, so it stays near its dot |

**Watch for a trailing spacer tipping a blank page.** If a section ends flush against the
footer, the engine can emit an entirely empty following page. Shave a line.

### Verification recipe — do not skip

```bash
python3 build_itinerary.py trips/<trip>.json
python3 - <<'PY'
import pypdfium2 as pdfium
d = pdfium.PdfDocument('output/<Name>.pdf')
for i in range(len(d)):
    n = len(d[i].get_textpage().get_text_range().strip())
    print(f'p{i+1} {n} chars' + ('  <-- SPARSE' if n < 300 and i else ''))
    d[i].render(scale=1.4).to_pil().save(f'output/page_{i+1:02d}.png')
PY
```

Then **look at every page image**. A sparse page is almost always an overflow that needs
content trimmed, not a layout bug. Delete the PNGs before committing.

---

## 6. Order of work

1. **`profiles.py`: `export` / `import`, and the honest empty-state message.**
   Smallest diff, stops silent data loss immediately. Ship this alone if nothing else.
2. **Markdown profile format + `migrate` + resolution order.**
3. **Privacy guards** — `.gitignore` entries and the pre-commit hook. Do this before any
   profile file exists locally, not after.
4. **SessionStart hook** — restores the profile and pre-seeds the map cache. Fixes §2 and
   §4 together.
5. **`fetch_data.py` mirror fallback.**
6. **`dining` schema + renderer + example.**
7. **Validator cross-checks** (needs §3.6 first). Highest ratio of bugs caught to lines
   written — do not stop before this.

Steps 1–3 are independent of 6–7 and can be done in either order. Step 4 depends on 2.

---

## 7. Notes for whoever implements this

- The PDF engine is proven; do not re-derive it. Every change above is additive.
- Keep presentation in the engine and content in the JSON. The schema docstring is explicit
  that formatting hacks must not appear in the data; honour it.
- `output/` is gitignored, so a rendered PDF cannot be committed. The trip JSON is the
  source of truth and rebuilds in about twenty seconds.
- Run both bundled examples after any engine change — they are the regression suite.
