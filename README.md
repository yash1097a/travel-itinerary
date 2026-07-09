# travel-itinerary (Claude Code plugin)

An interactive travel concierge for Claude Code. Plan a trip through a guided,
four-phase conversation (with approval gates) and generate a **polished, multi-page PDF
itinerary**. Each person keeps their **own preference profile**, stored locally on their
machine — nothing personal is shipped with the plugin.

Two skills:
- **`init`** — the friendly front door: readies the backend, greets you, and shows a menu of what
  you can do. **Start here.**
- **`plan-trip`** — the planner: Brief → Activities → Outline → Generate, each gated, ending
  in a downloadable PDF.
- **`travel-profile`** — conversational onboarding + manage your profile (create / list / show /
  update / delete / switch active). Supports multiple profiles (e.g. personal vs. family).

## Install

```
/plugin marketplace add yash1097a/travel-itinerary
/plugin install travel-itinerary
```

Then install the Python dependencies once (the planner uses them to render the PDF):

```
pip install -r "$CLAUDE_PLUGIN_ROOT/requirements.txt"
```

Best run in a cloud sandbox (e.g. **[claude.ai/code](https://claude.ai/code)**) so it works from
your phone or any computer.

## Use

Just run **`/travel-itinerary:init`** (or say *"get started"*). It sets things up, greets you,
and shows your options. From there:

1. **First time:** `/travel-itinerary:travel-profile` (or *"set up my travel profile"*) — a quick
   interview that saves your preferences locally.
2. **Plan:** `/travel-itinerary:plan-trip` — or say *"plan a relaxed 6-day trip to Portugal in
   October."* Answer through the phases, approve at each gate, and download the PDF.

If you run the planner before creating a profile, it will offer to onboard you first.

## Where your data lives

- **Profiles** and the **downloaded map data** live in your per-user Claude data directory
  (`~/.claude/plugins/data/travel-itinerary/`). They **survive plugin updates** and are never in
  this repo.
- The plugin ships **lean**: on the first trip it downloads ~70 MB of public-domain
  [Natural Earth](https://www.naturalearthdata.com/) map data once; every build after that is
  fully offline.

## What's inside

```
.claude-plugin/  plugin.json, marketplace.json
skills/
  init/          SKILL.md, status.py           (welcome + backend readiness)
  plan-trip/     SKILL.md, build_itinerary.py, fetch_data.py, STYLE.md,
                 schema/ (contract + validator + 2 example itineraries),
                 assets/ (EB Garamond font, Tabler icons)
  travel-profile/  SKILL.md, profiles.py, profile.schema.json
requirements.txt, .devcontainer/, LICENSE
```

## Licenses

MIT (this plugin). Bundled: EB Garamond (OFL), Tabler Icons (MIT). Natural Earth data is public
domain. See `LICENSE`.
