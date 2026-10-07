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

A profile is **one markdown file** — YAML frontmatter for the parts that get machine-checked
(diet, budget cap, mobility), prose for everything the planner reads. It is hand-editable,
diffable, and pasteable into any chat.

Profiles are looked up in this order, and the **first location that actually holds one wins**.
Every command tells you which one it used (`profiles.py where`):

| | Location | Notes |
|---|---|---|
| 1 | `$TRAVEL_PROFILE_PATH` | explicit override; a file or a directory |
| 2 | a private profile repo | see below — the answer for cloud sessions |
| 3 | `~/.claude/travel/profiles/` | local; point it at Dropbox/iCloud/OneDrive for free sync |
| 4 | `~/.claude/plugins/data/travel-itinerary/profiles/` | legacy JSON, **read-only**, converted on read |

Run `profiles.py migrate` to turn a legacy JSON profile into markdown. The JSON is left in place,
so it is safe to run.

### Cloud sessions: use a private repo

A cloud session (e.g. claude.ai/code) gets a **fresh, ephemeral container**. The data directory
does not survive it, so a profile saved in one session is gone in the next. A **private** git repo
is the only mechanism that needs no per-session step:

```
python3 "$CLAUDE_PLUGIN_ROOT/skills/travel-profile/profile_sync.py" setup <private-repo-url>
```

Then set `TRAVEL_PROFILE_REPO=<private-repo-url>` in your cloud environment, because the local
config file is ephemeral too. Each session runs `profile_sync.py pull` (the planner does this for
you) and `profile_sync.py push` after a change.

The clone is shallow, blobless and sparse to `profiles/`, so pointing it at a repo that also holds
large files costs almost nothing.

> **The repo must be private.** `setup` checks with the `gh` CLI and **refuses a public repo**,
> because a profile holds dietary restrictions, home airports, health constraints and travel
> history. If it cannot check, it says so.

- The **downloaded map data** lives in your per-user Claude data directory
  (`~/.claude/plugins/data/travel-itinerary/`) and survives plugin updates.
- **Never commit a profile to this repository.** It is public and distributed through a plugin
  marketplace, so a committed profile publishes dietary restrictions, home airports, health
  constraints and travel history. If you are working on the plugin itself, install the guard
  once — `git config core.hooksPath hooks` — and `hooks/pre-commit` will refuse any commit
  that stages a profile, including one forced in with `git add -f`.
- **On an ephemeral cloud container** (e.g. claude.ai/code) the data directory does **not**
  survive the session. Move a profile between machines with
  `profiles.py export` / `profiles.py import`.
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
