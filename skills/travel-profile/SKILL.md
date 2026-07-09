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
`set-active <name>`, `get-active-profile`, `dir`.

Pick the action from what the user asks. If it's ambiguous, ask.

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

**Then save it.** Build a JSON object shaped like `profile.schema.json`:

```json
{
  "profile_name": "default",
  "fixed_preferences": {
    "dietary_restrictions": "...", "dietary_preferences": "...", "photography": "...",
    "activities": "...", "pace": "...", "flights": "...", "lodging_structure": "..."
  },
  "ask_per_trip": { "group": "...", "budget": "...", "interests": "...", "lodging_style": "..." },
  "lodging_style_framework": { "...": "..." },
  "settings": { "research_depth": "light" }
}
```

Write it via stdin (this validates against the schema and makes the first profile active):

```bash
cat <<'JSON' | python3 "<this-skill-dir>/profiles.py" save "default"
{ ...the profile json... }
JSON
```

Confirm what was saved and where (`profiles.py dir`), and tell them the planner will now use it.

---

## Other actions

- **List:** `profiles.py list` (the active one is marked `*`).
- **Show:** `profiles.py show <name>` — read it back to the user in plain language.
- **Update:** `show` the current profile, ask what to change, then `save <name>` the full updated
  JSON (save overwrites). Keep everything they didn't change.
- **Delete:** confirm first, then `profiles.py delete <name>`.
- **Switch active:** `profiles.py set-active <name>` — used when someone keeps multiple profiles
  (e.g. a personal one and a "family" one).

## Rules
- Profiles are **local user data** — never write them into the plugin folder or a repo.
- Store **clean, human-readable** preference text; the planner interprets it.
- Keep the **fixed vs ask-per-trip** split — don't bake trip-specific choices (budget, group) into
  fixed preferences.
