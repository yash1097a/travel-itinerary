#!/usr/bin/env python3
"""
Sync the traveller profile with a PRIVATE git repo, so it survives an ephemeral
cloud container and is shared between machines.

Why a repo: the profile store lives outside the plugin repo by design, which is right
on a laptop and useless in the cloud, where the whole container is reclaimed at the
end of a session. A private repo is the one mechanism that needs no per-session step.

The clone is deliberately cheap -- shallow, blobless, and sparse to `profiles/` only --
so pointing this at a repo that also holds large files costs nothing.

    profile_sync.py check <repo>       # can this environment reach it? is it private? (writes nothing)
    profile_sync.py setup <repo>       # check, record the repo, then pull
    profile_sync.py adopt              # copy profiles saved on this machine into the repo
    profile_sync.py pull               # clone or fast-forward; never fails a session
    profile_sync.py push [-m MSG]      # commit and push changed profiles
    profile_sync.py status

PRIVACY: the target repo must be PRIVATE. A profile holds dietary restrictions, home
airports, health constraints and travel history. `setup` refuses a repo that GitHub
reports as public when the `gh` CLI is available to check, and warns when it cannot.

`pull` never fails a session (exit 0 when it gives up), so its FIRST line of output is a
marker the skills must read. A failed pull is not the same as having no repo:

    PROFILE_REPO_OK              cloned or fast-forwarded; the repo's profiles are loaded
    PROFILE_REPO_NOT_CONFIGURED  no repo set ($TRAVEL_PROFILE_REPO or config.json)
    PROFILE_REPO_UNREACHABLE     a repo IS configured but could not be cloned, so the user's
                                 saved profile is NOT loaded. Followed by `reason: auth |
                                 not_found | network | unknown`. Never re-onboard on this.
    PROFILE_REPO_STALE           a clone exists but the fetch failed; using the local copy

`check` and `setup` take a full URL or GitHub shorthand (`owner/name`). Their first line is
REPO_OK, REPO_PUBLIC or REPO_UNREACHABLE (plus `reason:`), and `setup` records nothing unless
the repo is reachable and not public.

STDLIB ONLY (subprocess is stdlib) -- this runs before dependencies are installed.
"""
import os
import sys
import re
import json
import argparse
import subprocess

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import profile_store as store

SPARSE_DIR = "profiles"


def _run(args, cwd=None, check=True, quiet=False):
    """Run a command, returning (rc, stdout+stderr)."""
    # Never block on an interactive credential prompt: a skill runs this unattended, and
    # in a cloud container there is nobody to answer it. Credential helpers still work.
    env = dict(os.environ, GIT_TERMINAL_PROMPT="0")
    try:
        p = subprocess.run(args, cwd=cwd, stdout=subprocess.PIPE,
                           stderr=subprocess.STDOUT, text=True, encoding="utf-8",
                           errors="replace", env=env)
    except FileNotFoundError:
        return 127, "{} not found on PATH".format(args[0])
    out = (p.stdout or "").strip()
    if check and p.returncode != 0 and not quiet:
        pass
    return p.returncode, out


def _git(args, cwd=None, quiet=False):
    return _run(["git"] + args, cwd=cwd, quiet=quiet)


def _redact(text):
    """Strip credentials from URLs (https://user:token@host) before printing."""
    return re.sub(r"(https?://)[^/@\s]+@", r"\1***@", text or "")


def _failure_reason(out):
    """Classify a failed clone from git's own words, so the skill can say what to fix."""
    o = (out or "").lower()
    # Network first: a proxy refusing the tunnel also says "403", but it is egress policy,
    # not a credentials problem.
    if any(k in o for k in ("tunnel failed", "could not resolve host", "timed out",
                            "connection refused", "connection reset", "proxy",
                            "network is unreachable")):
        return "network"
    if any(k in o for k in ("could not read username", "authentication failed",
                            "terminal prompts disabled", "permission denied",
                            "returned error: 403", "returned error: 401",
                            "invalid username or password")):
        return "auth"
    if "not found" in o or "does not exist" in o:
        return "not_found"   # GitHub also says this for a private repo you can't see
    return "unknown"


REASON_HINT = {
    "auth": "no GitHub credentials for this repo in this environment. In a cloud session, "
            "start it with the profile repo selected (or attach it), or connect GitHub.",
    "not_found": "the repo does not exist, or this account cannot see it (GitHub reports a "
                 "private repo you lack access to as not found). Check the URL and access.",
    "network": "the git host could not be reached (offline, or blocked by network policy).",
    "unknown": "see git's message below.",
}


def _is_clone(d):
    return os.path.isdir(os.path.join(d, ".git"))


def _default_branch(d):
    rc, out = _git(["symbolic-ref", "--short", "HEAD"], cwd=d, quiet=True)
    if rc == 0 and out:
        return out
    return "main"


def _is_empty(d):
    """A freshly created repo with no commits yet (an unborn branch)."""
    return _git(["rev-parse", "--verify", "-q", "HEAD"], cwd=d, quiet=True)[0] != 0


def in_cloud():
    """A claude.ai cloud session: an ephemeral container, where only an environment
    setting (not ~/.claude/travel/config.json) survives to the next session."""
    return os.environ.get("CLAUDE_CODE_REMOTE", "").lower() == "true"


def normalise_url(arg):
    """Accept https/ssh URLs as given; turn GitHub shorthand into an https URL.
        yash/travel-profiles             -> https://github.com/yash/travel-profiles.git
        github.com/yash/travel-profiles  -> https://github.com/yash/travel-profiles.git
    """
    a = (arg or "").strip()
    if re.match(r"^(https?|ssh|git|file)://", a) or a.startswith("git@"):
        return a
    a = re.sub(r"^(www\.)?github\.com/", "", a).rstrip("/")
    if a.endswith(".git"):
        a = a[:-4]
    if re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", a):
        return "https://github.com/{}.git".format(a)
    return arg


# ── Privacy check ─────────────────────────────────────────────────────────────
def _repo_slug(url):
    """owner/name from an https or ssh GitHub URL, else ''."""
    u = url.strip().rstrip("/")
    if u.endswith(".git"):
        u = u[:-4]
    for pre in ("https://github.com/", "http://github.com/",
                "git@github.com:", "ssh://git@github.com/"):
        if u.startswith(pre):
            return u[len(pre):]
    return ""


def visibility(url):
    """('private' | 'public' | 'unknown', human note). Uses the gh CLI when it can."""
    slug = _repo_slug(url)
    if not slug:
        return "unknown", "not a GitHub URL, so visibility could not be checked"
    # REST, not `gh repo view`: that uses GraphQL, which some environments (claude.ai cloud
    # sessions among them) block.
    rc, out = _run(["gh", "api", "repos/" + slug])
    if rc != 0:
        first = out.splitlines()[0] if out else "gh unavailable"
        try:                       # gh prints the API's JSON error body; keep its message
            first = json.loads(out).get("message") or first
        except Exception:
            pass
        return "unknown", "could not ask GitHub ({})".format(
            first if len(first) <= 80 else first[:77] + "...")
    try:
        info = json.loads(out)
    except Exception:
        return "unknown", "could not parse gh output"
    return ("private" if info.get("private") else "public"), "checked via the GitHub API"


# ── Commands ──────────────────────────────────────────────────────────────────
def _check(url):
    """Print REPO_OK / REPO_PUBLIC / REPO_UNREACHABLE for url. Returns (ok, empty)."""
    vis, how = visibility(url)
    if vis == "public":
        print("REPO_PUBLIC")
        print("repo: " + _redact(url))
        print("This repo is PUBLIC. A traveller profile holds dietary restrictions, home")
        print("airports, health constraints and travel history: it must go in a PRIVATE repo.")
        print("Make it private on GitHub (Settings -> General -> Danger Zone), or use another.")
        return False, False
    rc, out = _git(["ls-remote", "--heads", url])
    if rc != 0:
        reason = _failure_reason(out)
        print("REPO_UNREACHABLE")
        print("reason: " + reason)
        print("repo: " + _redact(url))
        print("Why: " + REASON_HINT[reason])
        print("git said:")
        print("  " + "\n  ".join(_redact(out).splitlines()[:6]))
        return False, False
    empty = not out.strip()
    print("REPO_OK")
    print("repo: " + _redact(url))
    print("visibility: {} ({})".format(vis, how))
    if vis == "unknown":
        print("  Could not confirm it is private. Make sure it is before saving a profile.")
    print("empty: " + ("yes -- the first profile save will populate it" if empty else "no"))
    print("environment: " + ("cloud (ephemeral container)" if in_cloud() else "local"))
    return True, empty


def cmd_check(a):
    ok, _empty = _check(normalise_url(a.url))
    return 0 if ok else 1


def cmd_setup(a):
    url = normalise_url(a.url)
    ok, _empty = _check(url)
    if not ok:
        print()
        print("Nothing recorded. Fix the above, then run setup again.")
        return 1
    cfg = store.read_config()
    cfg["profile_repo"] = url
    if a.dir:
        cfg["profile_repo_dir"] = os.path.abspath(os.path.expanduser(a.dir))
    path = store.write_config(cfg)
    print()
    print("Recorded profile repo in {}".format(path))
    env = os.environ.get("TRAVEL_PROFILE_REPO")
    if env and normalise_url(env) != url:
        print("NOTE: $TRAVEL_PROFILE_REPO is set to a different repo ({}) and takes precedence"
              .format(_redact(env)))
        print("      over this config. Change or remove it so the two agree.")
    if in_cloud() and normalise_url(env or "") != url:
        # The config file lives in the container and is reclaimed with it.
        print("PERSIST_IN_ENVIRONMENT")
        print("This is a cloud session: the config file above is deleted with the container.")
        print("So the next session finds the repo, add this environment variable to the")
        print("cloud environment's settings:")
        print("    TRAVEL_PROFILE_REPO={}".format(_redact(url)))
        print("and select this repo alongside the plugin repo when starting a session, so the")
        print("session has GitHub access to it.")
    print()
    return cmd_pull(a)


def cmd_adopt(a):
    """Copy markdown profiles from the local store into the repo clone, without
    overwriting any that are already there. Then `push` shares them."""
    if not store.profile_repo():
        sys.exit("No profile repo configured. Run: profile_sync.py setup <private-repo-url>")
    d = store.repo_clone_dir()
    if not _is_clone(d):
        sys.exit("The profile repo is not cloned yet. Run: profile_sync.py pull")
    src = store.local_profiles_dir()
    dst = os.path.join(d, SPARSE_DIR)
    os.makedirs(dst, exist_ok=True)
    names = sorted(f for f in os.listdir(src) if f.endswith(".md")) if os.path.isdir(src) else []
    copied, skipped = [], []
    for f in names:
        target = os.path.join(dst, f)
        if os.path.exists(target):
            skipped.append(f[:-3])
            continue
        with open(os.path.join(src, f), encoding="utf-8") as i, \
                open(target, "w", encoding="utf-8", newline="\n") as o:
            o.write(i.read())
        copied.append(f[:-3])
    if not names:
        print("No profiles saved on this machine ({}) -- nothing to adopt.".format(src))
        return 0
    if copied:
        print("Copied into the repo: " + ", ".join(copied))
        print("Share them with: profile_sync.py push")
    if skipped:
        print("Already in the repo, left alone (the repo copy wins): " + ", ".join(skipped))
    return 0


def cmd_pull(a):
    """Clone or fast-forward. Never fails the caller: a session must still work offline."""
    url = store.profile_repo()
    if not url:
        print("PROFILE_REPO_NOT_CONFIGURED")
        print("No profile repo configured. Run: profile_sync.py setup <private-repo-url>")
        return 0
    d = store.repo_clone_dir()
    if not _is_clone(d):
        os.makedirs(os.path.dirname(d) or ".", exist_ok=True)
        rc, out = _git(["clone", "--depth", "1", "--filter=blob:none", "--no-checkout",
                        url, d])
        if rc != 0:
            return _unreachable(url, out)
        _git(["sparse-checkout", "init", "--cone"], cwd=d)
        _git(["sparse-checkout", "set", SPARSE_DIR], cwd=d)
        if _is_empty(d):
            # A brand-new repo: nothing to check out, and that is fine.
            print("PROFILE_REPO_OK")
            print("Cloned the profile repo -> {} (it is empty so far)".format(d))
        else:
            rc, out = _git(["checkout"], cwd=d)
            if rc != 0:
                return _unreachable(url, out)
            print("PROFILE_REPO_OK")
            print("Cloned profile repo (shallow, sparse to {}/) -> {}".format(SPARSE_DIR, d))
    else:
        rc, out = _git(["fetch", "--depth", "1", "origin"], cwd=d)
        if rc != 0:
            print("PROFILE_REPO_STALE")
            print("reason: " + _failure_reason(out))
            print("Could not reach the profile repo -- using the local copy in " + d)
            return 0
        dirty = _git(["status", "--porcelain"], cwd=d)[1]
        if dirty:
            print("PROFILE_REPO_OK")
            print("Local profile changes not yet pushed -- NOT overwriting them:")
            for line in dirty.splitlines()[:10]:
                print("  " + line)
            print("Push them with: profile_sync.py push")
            return 0
        br = _default_branch(d)
        if _git(["rev-parse", "--verify", "-q", "origin/" + br], cwd=d, quiet=True)[0] == 0:
            _git(["reset", "--hard", "origin/" + br], cwd=d)
        elif _git(["rev-parse", "--verify", "-q", "FETCH_HEAD"], cwd=d, quiet=True)[0] == 0:
            _git(["reset", "--hard", "FETCH_HEAD"], cwd=d)
        # else: the remote is still empty -- nothing to update to.
        print("PROFILE_REPO_OK")
        print("Profile repo up to date ({}).".format(d))

    pdir = os.path.join(d, SPARSE_DIR)
    if not os.path.isdir(pdir):
        os.makedirs(pdir, exist_ok=True)
        print("(repo has no {}/ yet -- created it; the first save will populate it)"
              .format(SPARSE_DIR))
    names = sorted(f[:-3] for f in os.listdir(pdir) if f.endswith(".md"))
    print("Profiles available from the repo: " + (", ".join(names) if names else "none yet"))
    return 0


def _unreachable(url, out):
    """A repo is configured but could not be cloned. Loud, but still exit 0: the session
    must carry on. The marker tells the skill not to treat this as a new user."""
    reason = _failure_reason(out)
    print("PROFILE_REPO_UNREACHABLE")
    print("reason: " + reason)
    print("repo: " + _redact(url))
    print("The traveller's saved profile is in that repo and was NOT loaded.")
    print("Why: " + REASON_HINT[reason])
    print("git said:")
    print("  " + "\n  ".join(_redact(out).splitlines()[:6]))
    return 0


def cmd_push(a):
    url = store.profile_repo()
    if not url:
        sys.exit("No profile repo configured. Run: profile_sync.py setup <private-repo-url>")
    d = store.repo_clone_dir()
    if not _is_clone(d):
        sys.exit("The profile repo is not cloned yet. Run: profile_sync.py pull")
    _git(["add", "--", SPARSE_DIR], cwd=d)
    staged = _git(["diff", "--cached", "--name-only"], cwd=d)[1]
    if not staged:
        print("Nothing to push -- the repo already matches the local profile.")
        return 0
    msg = a.message or "Update traveller profile"
    rc, out = _git(["-c", "user.name=travel-itinerary",
                    "-c", "user.email=travel-itinerary@localhost",
                    "commit", "-m", msg], cwd=d)
    if rc != 0:
        print("Could not commit:")
        print("  " + "\n  ".join(out.splitlines()[:8]))
        return 1
    br = _default_branch(d)
    rc, out = _git(["push", "origin", "HEAD:" + br], cwd=d)
    if rc != 0:
        print("Committed locally but could not push:")
        print("  " + "\n  ".join(out.splitlines()[:8]))
        print("Retry with: profile_sync.py push")
        return 1
    print("Pushed to {} ({}):".format(url, br))
    for line in staged.splitlines():
        print("  " + line)
    return 0


def cmd_status(a):
    url = store.profile_repo()
    d = store.repo_clone_dir()
    print("Configured repo: " + (_redact(url) or "(none)"))
    print("Config file:     " + store.config_path()
          + ("" if os.path.exists(store.config_path()) else "  (absent)"))
    print("Env override:    " + (_redact(os.environ.get("TRAVEL_PROFILE_REPO")) or "(not set)"))
    print("Clone dir:       " + d + ("" if _is_clone(d) else "  (not cloned)"))
    if _is_clone(d):
        print("Branch:          " + _default_branch(d))
        dirty = _git(["status", "--porcelain"], cwd=d)[1]
        print("Unpushed edits:  " + (dirty if dirty else "none"))
    print()
    print("Profile resolution:")
    for line in store.store_report():
        print(line)
    return 0


def main():
    ap = argparse.ArgumentParser(description="Sync the traveller profile with a private git repo.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("check"); p.add_argument("url"); p.set_defaults(fn=cmd_check)
    p = sub.add_parser("setup"); p.add_argument("url"); p.add_argument("--dir")
    p.set_defaults(fn=cmd_setup)
    sub.add_parser("adopt").set_defaults(fn=cmd_adopt)
    sub.add_parser("pull").set_defaults(fn=cmd_pull)
    p = sub.add_parser("push"); p.add_argument("-m", "--message"); p.set_defaults(fn=cmd_push)
    sub.add_parser("status").set_defaults(fn=cmd_status)
    a = ap.parse_args()
    sys.exit(a.fn(a) or 0)


if __name__ == "__main__":
    main()
