---
name: travel-profile
description: Create, view, update, delete, or switch a traveller preference profile used by the travel-itinerary planner. Use when the user wants to set up their travel preferences, onboard, edit their profile, manage multiple profiles (e.g. themselves vs family vs friends), or when the planner reports no profile exists yet. Runs a friendly conversational onboarding for new profiles.
---

# Travel Profile Manager

You manage **traveller preference profiles** for the travel-itinerary planner. Profiles are
stored **per-user, on this machine only** (never in the plugin, never committed), via the
helper script alongside this file:

    python3 "<this-skill-dir>/profiles.py" <command>

Resolve `<this-skill-dir>` as the folder containing this SKILL.md (use `$CLAUDE_PLUGIN_ROOT/skills/travel-profile` if set). Commands:
`list`, `show <name>`, `save <name>` (JSON on stdin), `delete <name>`, `get-active`,
`set-active <name>`, `get-active-profile`, `export [name]`, `import [name]` (JSON on stdin),
`dir`, `where`.

Pick the action from what the user asks. If it's ambiguous, ask.

## Moving a profile between machines

The store lives outside the repo, which means **an ephemeral cloud container does not keep it** —
the profile goes when the session is reclaimed. Two commands cover this:

- **`export [name]`** — writes the profile JSON to stdout (defaults to the active one). Offer this
  whenever someone has just onboarded in a cloud session, so they have a copy to paste back.
- **`import [name]`** — reads profile JSON from stdin and saves it. The name comes from the
  argument, else the JSON's own `profile_name`, else `default`.

```bash
python3 "<this-skill-dir>/profiles.py" export > my-travel-profile.json
python3 "<this-skill-dir>/profiles.py" import < my-travel-profile.json
```

If a command reports **`PROFILE_STORE_MISSING`**, no store exists at all — on a fresh container
that usually means a previous profile was lost with it, not that the user is new. Show the paths
it listed, say so plainly, and offer `import` before offering to re-onboard. **`where`** prints
every candidate location and which one is in use, including profiles sitting in a location that
is not being read.

**Never commit a profile to a repository.** The plugin repo is public; `hooks/pre-commit` there
refuses any commit that stages one.

---

## Create a profile (onboarding)

Run a warm, conversational interview — **one or two questions at a time, not a wall of forms**.
Offer sensible defaults and let them skip. Cover these dimensions, then assemble the JSON:

**Fixed preferences (always apply):**
1. **Dietary restrictions** — vegetarian / vegan / none / allergies? Capture nuances precisely
   (e.g. "lacto-veg; eggs only baked into things, never as a dish"). Use "none" if unrestricted.
2. **Dietary preferences** — cuisines they love/avoid, coffee, alcohol (none/light/enthusiast),
   appetite for local specialties.
3. **Photography / hobbies** — any camera or photography interest that should shape stops & light.
4. **Activities** — durable likes (scenic drives, hikes and how strenuous, water sports for beach
   trips, biking, etc.).
5. **Pace** — relaxed vs active; are fuller days OK; early starts for light?
6. **Flights** — home airport(s), airline loyalty/cards, and how flexible (willing to switch for
   a cheaper/better option?).
7. **Lodging format** — default is: *neighbourhood + 2–3 suggested properties (with a reason each)
   + rationale, no prices*. Keep unless they want something else.

**Ask-per-trip (record as guidance, don't pin values):**
- **Group** — do trips vary (couple / family / friends)?
- **Budget** — set per trip, or a usual tier?
- **Interests / trip focus** — do these vary by destination?
- **Lodging style framework** — e.g. *beach/hills retreat → boutique/resort*; *city/parks/new
  country → well-located but cost-optimised*. Capture their rule.

**Settings:**
- **Research depth** — explain plainly and let them choose:
  *"When I plan, I can do **light** research (I lean on what I already know plus a few key checks
  — fast, reliable to finish, and easy on your usage limits) or **heavy** research (I verify
  everything against live sources and dig deep — more thorough, but it uses a lot more of your
  usage allowance and can stall on stricter plans)."*
  Recommend **light** unless they know they have generous limits. Store as `settings.research_depth`
  = `"light"` or `"heavy"`. Default to `"light"` if they're unsure.

**Two things to collect that are easy to skip and cause real planning errors:**

- **How strict the diet actually is.** The label is not the rule. "Vegetarian" does not say
  whether eggs baked into a cake are fine. Ask where they draw the line and record their
  own words in `diet.strictness` — without it the planner invents a stricter or looser rule
  than they hold.
- **A per-meal number.** Ask what they would rather not go over for a normal dinner, and store
  it as `budget.per_meal_cap` with a currency. Without a number the planner reaches for a
  headline meal several times what they intended to spend. If they genuinely do not want a cap,
  leave it `null` — but ask.

Also ask whether any **mobility** constraint applies right now. If it is temporary, set
`mobility.review_after` to a date, so it expires instead of quietly applying to every future trip.

**Then save it.** A profile is one markdown file: YAML frontmatter for the parts that must be
machine-checked, prose for everything you interpret.

```markdown
---
schema_version: 2
profile_name: default
updated: <today, ISO>
settings:
  research_depth: light          # light | heavy
diet:
  restriction: vegetarian        # the short label
  strictness: >
    Their own words on where the line actually is.
budget:
  per_meal_cap: 50               # null only if they declined a cap
  currency: USD
  tier: mid-range
mobility:
  status: none                   # none | temporary | ongoing
  review_after: null             # a date when status is temporary
---

# Traveller profile — <name>

## Diet
## Food preferences
## Photography
## Activities
## Pace
## Mobility
## Flights
## Lodging format
## Ask per trip
## Trip log
```

Write prose under each heading — full sentences, their nuances kept. `## Photography` should
name **bodies and lenses**, not just "likes photography": it changes what is worth recommending.
`## Ask per trip` records the *rules* for group, budget, focus and lodging style, not pinned
values. Leave `## Trip log` with a short placeholder; add three lines per trip (where, when,
what worked) as trips happen — that is what makes the profile compound rather than merely
persist, and it stops a later session pitching somewhere already done.

Save it via stdin:

```bash
python3 "<this-skill-dir>/profiles.py" save "default" <<'MD'
---
schema_version: 2
...the full markdown profile...
MD
```

Then **confirm where it went** (`profiles.py where`) and tell them the planner will use it.
If a private profile repo is configured, offer to push it now
(`profile_sync.py push`) — until that happens it exists only on this machine.

---

## Other actions

- **List:** `profiles.py list` (the active one is marked `*`, grouped by where it lives).
- **Show:** `profiles.py show <name>` — read it back to the user in plain language.
- **Update:** `show` the current profile, ask what to change, then `save <name>` the full updated
  markdown (save overwrites). Keep everything they didn't change, and bump `updated`.
- **Delete:** confirm first, then `profiles.py delete <name>`.
- **Switch active:** `profiles.py set-active <name>` — used when someone keeps multiple profiles
  (e.g. a personal one and a "family" one).
- **Migrate:** `profiles.py migrate` converts a legacy JSON profile to markdown. The JSON is left
  in place and still readable, so this is safe to run.

**Amend immediately, never at the end.** There is no reliable end-of-session here — tabs close,
turns get interrupted, containers are reclaimed. If the user changes a preference mid-conversation,
`save` it then and there, and push if a repo is configured. A design that persists only at the end
loses exactly the sessions that ended badly.

## Rules
- Profiles are **personal data** — never write them into the plugin folder or any public repo.
  The plugin repo's `hooks/pre-commit` refuses a commit that stages one.
- A **private** repo is the only repo a profile may go in. `profile_sync.py setup` refuses a public
  one outright.
- Store **clean, human-readable** preference text; the planner interprets it.
- Keep the **durable vs ask-per-trip** split — don't bake trip-specific choices (budget for one
  trip, group for one trip) into the durable sections.
- Keep `diet.strictness` in the traveller's **own words**. Don't normalise it into a label; the
  label is already `diet.restriction`.
