# Private profile repo: setup and connect

A guided flow, shared by the `init` and `travel-profile` skills. Use it when **no profile was found**,
or when the user asks to set up or connect their profile repo.

**Why a repo:** a profile saved on this machine lives outside the plugin. On a laptop that's fine.
In a cloud session the whole container is deleted at the end, and the profile goes with it. A
**private** GitHub repo is the one place a profile survives across sessions and machines.

Scripts (in this folder; `$CLAUDE_PLUGIN_ROOT/skills/travel-profile/` when that is set):

```bash
python3 profile_sync.py check <repo>   # reachable? private? empty? Writes nothing.
python3 profile_sync.py setup <repo>   # check, record it, clone it
python3 profile_sync.py adopt          # copy profiles saved on this machine into the repo
python3 profile_sync.py push           # share changes
```

`<repo>` can be a full URL or GitHub shorthand (`owner/name`). `check` and `setup` lead with a
marker: `REPO_OK`, `REPO_PUBLIC` or `REPO_UNREACHABLE` plus `reason: auth | not_found | network`.
`setup` records nothing unless the repo is reachable and not public. In a cloud session it also
prints `PERSIST_IN_ENVIRONMENT` with the exact line to add to the environment's settings.

Read `environment` from `status.py`'s `STATUS_JSON` (`cloud` or `local`). The steps differ.

---

## Step 0: ask one question

Never assume, and never start onboarding before asking. Ask (use a multiple-choice question
if your tools offer one):

> I couldn't find a travel profile. Profiles are kept in a **private GitHub repo** so they're
> there in every session. Have you already made one?
>
> 1. **Yes, I have a repo**: let's connect it.
> 2. **No, help me set one up**: takes about two minutes.
> 3. **Not now**: keep my profile on this machine only.

In a **cloud** session, add one line to option 3: *"It'll be deleted when this session ends."*

Then follow **A**, **B** or **C** below.

---

## A. They already have a repo: connect it

1. **Ask which repo.** `owner/name` is enough. If they're unsure, the URL of the repo page works.
2. **Check it:** `profile_sync.py check <repo>`.
   - `REPO_OK`: go to step 4.
   - `REPO_PUBLIC`: stop. Explain that a profile holds diet, health and travel details, so it can't
     go in a public repo. They can make it private on GitHub (repo **Settings → General → Danger
     Zone → Change visibility**) and you check again, or they can use another repo.
   - `REPO_UNREACHABLE`: go to step 3.
3. **Give this environment access**, depending on `reason:`.
   - `auth`, **cloud**: this session can only reach the repos it was given. In order:
     - If you have a tool that attaches a repository to the session, offer to attach it now (it
       needs push access, so saves can be shared), then run `check` again.
     - Otherwise the Claude GitHub App may not be installed on that repo. They can connect GitHub
       at https://claude.ai/connect-github and install the app on the repo there, then start a
       **new** session with the profile repo selected beside the plugin repo.
   - `auth`, **local**: their own git login is missing for this repo. Have them check that
     `git clone <url>` works in their terminal (for example, `gh auth login`, or set up an SSH key),
     then run `check` again.
   - `not_found`: confirm the spelling of `owner/name`. GitHub also says "not found" for a private
     repo this account can't see, so treat it like `auth` if the name is right.
   - `network`: GitHub couldn't be reached (offline, or blocked by the environment's network
     policy). Say so, and offer option C for now.
4. **Record and clone it:** `profile_sync.py setup <repo>`. It ends with the pull marker; expect
   `PROFILE_REPO_OK` and a list of the profiles found.
5. **Make it stick** (see **Keep it connected** below).
6. **Load the profile.** If the repo holds profiles, greet them by the active one and carry on;
   no interview needed. If it's empty, offer onboarding (the profile saves straight into the
   repo), then `push`.

---

## B. No repo yet: set one up

Keep each step short and wait for them between steps that need them to act.

1. **Create a private repo on GitHub.**
   - **Local, `gh` CLI installed and logged in**: offer to run it for them, and run it only with
     a yes:
     ```bash
     gh repo create travel-profiles --private --description "My travel-itinerary profiles"
     ```
   - **Otherwise**: have them open https://github.com/new, name it (suggest `travel-profiles`),
     choose **Private**, and click **Create repository**. Nothing else on that page matters.
     An empty repo is fine.

   Then ask for `owner/name`.
2. **Give this environment access**: the same as **A**, step 3. In a cloud session a brand-new
   repo is never in the session yet, so this step always applies there: attach it if you can, or
   install the Claude GitHub App on it at https://claude.ai/connect-github.
3. **Check, record and clone it:** `profile_sync.py setup <repo>`. Handle the markers as in **A**.
4. **Make it stick** (see below).
5. **Fill it.**
   - If a profile is already saved on this machine (`profiles.py where` lists one under
     `local`), run `profile_sync.py adopt`, then `push`.
   - Otherwise run the onboarding in `travel-profile/SKILL.md`. With a repo configured, `save`
     writes into it. Then `push`.
6. **Confirm**, in one line: the profile is saved in `owner/name` and will load in every session.

---

## C. Not now

Run the normal onboarding and save locally. In a **cloud** session, say plainly that the profile
will be deleted with this session, offer `profiles.py export` so they keep a copy, and mention
they can set up the repo any time with *"set up my profile repo"*.

---

## Keep it connected

`setup` writes the repo to `~/.claude/travel/config.json`. That's enough **locally**: every future
session reads it.

In a **cloud** session that file is deleted with the container. When `setup` prints
`PERSIST_IN_ENVIRONMENT`, walk them through two settings in the cloud environment (the environment
menu in the session's title bar, then **Edit**):

1. **Environment variable:** add the `TRAVEL_PROFILE_REPO=...` line `setup` printed. That tells
   future sessions where the profile lives.
2. **Repositories:** add the profile repo, where that section is offered, so every session gets
   GitHub access to it. Otherwise they need to select it beside the plugin repo each time they
   start a session.

Both are needed: the variable says *where*, the repo access lets the session *reach* it. Missing
access is exactly what makes a later startup report `PROFILE_REPO_UNREACHABLE`.

Never ask anyone to paste a token, password or key into the chat. Access comes from the GitHub App
or their own git login, never from a credential typed into a session.
