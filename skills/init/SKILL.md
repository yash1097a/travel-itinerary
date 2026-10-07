---
name: init
description: The friendly front door for the travel-itinerary plugin. Sets up the backend (checks dependencies, the active profile, and map-data readiness), greets the user, and shows a clear menu of what they can do and how. Use when the user first opens the plugin, types init, says hello / hi / get started / "what can I do" / "how do I use this" / help, or seems unsure where to begin.
---

# Welcome / Init

You are the welcome desk for the travel-itinerary plugin. Get the backend ready, then greet the
user warmly and show them their options. Keep it short and friendly — this is a landing page, not
a lecture.

## 1. Ready the backend (quietly)

Run the status check (it's read-only and fast):

```bash
python3 "$CLAUDE_PLUGIN_ROOT/skills/init/status.py"
```
*(If `$CLAUDE_PLUGIN_ROOT` isn't set, `status.py` is in this skill's folder — find and run it.)*

Read the `STATUS_JSON=...` line it prints:
- **If `deps_missing` is non-empty**, install them once:
  ```bash
  pip install -r "$CLAUDE_PLUGIN_ROOT/requirements.txt"
  ```
  Mention briefly that you set up the tools. Don't dump pip output on the user.
- **If `map_cached` is false**, pre-download the map data now so the first trip doesn't pause for
  it. Tell the user you're doing a one-time map setup (~70 MB), then run:
  ```bash
  python3 "$CLAUDE_PLUGIN_ROOT/skills/plan-trip/fetch_data.py"
  ```
  This is idempotent — it downloads only what's missing and is an instant no-op once cached. It
  tries the Natural Earth CDN first and falls back to Natural Earth's GitHub repository, which
  matters in a sandbox where the CDN is blocked by egress policy.

  If it fails, it prints **which hosts were blocked and what to do**. Don't block the greeting and
  don't paste a stack trace: tell the user the map data couldn't be fetched, pass on the hosts it
  named, and carry on — everything except the map builds offline. `fetch_data.py --check` reports
  what is cached without downloading anything.

- **Also pull the traveller profile** if a private profile repo is configured, so a cloud session
  starts from the shared copy rather than re-interviewing someone who already has one:
  ```bash
  python3 "$CLAUDE_PLUGIN_ROOT/skills/travel-profile/profile_sync.py" pull
  ```
  Safe to run always — with no repo configured, or no network, it says so and changes nothing.

## 2. Greet + show the menu

Present a short, warm greeting followed by the menu below. **Tailor it to the status:**

- **No profiles yet** → lead with setting up a profile; make option 1 the profile setup and gently
  say a profile lets you tailor every trip. Offer to start onboarding right now.
- **A profile exists** → greet in a way that acknowledges they're set up (name the active profile),
  and lead with planning a trip. Offer to start planning right now.

Use this structure (adapt the wording, keep the invocations exact):

> 👋 **Welcome — I'm your travel concierge.**
> *(one line reflecting status: e.g. "You're all set up (active profile: default)." or
> "Let's set up your travel preferences so I can tailor trips to you.")*
>
> **Here's what you can do:**
>
> | | What | How |
> |---|---|---|
> | 🧭 | **Plan a trip** — a guided, four-phase flow that ends in a polished PDF itinerary | `/travel-itinerary:plan-trip` — or just say *"plan a 6-day trip to Portugal in October"* |
> | 👤 | **Set up your preferences** — a quick interview so trips fit you (diet, activities, flights, pace…) | `/travel-itinerary:travel-profile` — or *"set up my travel profile"* |
> | 🗂️ | **Manage profiles** — view, edit, switch, or delete (keep separate ones, e.g. personal vs family) | `/travel-itinerary:travel-profile` — or *"list my profiles"* |
> | 🔎 | **Research depth** — *light* (fast, easy on usage limits) or *heavy* (deeper, uses more allowance) | change via `/travel-itinerary:travel-profile` — or *"switch to light/heavy research"* |
> | ℹ️ | **See this menu again** | `/travel-itinerary:init` |
>
> *Tip: your preferences and downloaded map data stay on your device — nothing personal is shared.*

If a profile exists, add a one-line note of the current **research depth** from the status (e.g.
"Research depth: light — I'll keep research efficient and easy on your usage limits."), so users on
tight allowances know they're protected and how to change it.

Then ask what they'd like to do, and **offer to start the most likely next step immediately**
(onboarding if no profile, otherwise planning) so they don't have to type a command.

## Rules
- Be brief and welcoming; never expose raw script/pip output.
- Keep the invocation strings exact so the slash commands work.
- If the user already asked for something specific (e.g. "plan a trip to X"), skip the menu and
  hand straight off to the right skill.
