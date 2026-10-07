#!/usr/bin/env python3
"""
Sync the traveller profile with a PRIVATE git repo, so it survives an ephemeral
cloud container and is shared between machines.

Why a repo: the profile store lives outside the plugin repo by design, which is right
on a laptop and useless in the cloud, where the whole container is reclaimed at the
end of a session. A private repo is the one mechanism that needs no per-session step.

The clone is deliberately cheap -- shallow, blobless, and sparse to `profiles/` only --
so pointing this at a repo that also holds large files costs nothing.

    profile_sync.py setup <repo-url>   # record the repo, then pull
    profile_sync.py pull               # clone or fast-forward; never fails a session
    profile_sync.py push [-m MSG]      # commit and push changed profiles
    profile_sync.py status

PRIVACY: the target repo must be PRIVATE. A profile holds dietary restrictions, home
airports, health constraints and travel history. `setup` refuses a repo that GitHub
reports as public when the `gh` CLI is available to check, and warns when it cannot.

STDLIB ONLY (subprocess is stdlib) -- this runs before dependencies are installed.
"""
import os
import sys
import json
import argparse
import subprocess

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import profile_store as store

SPARSE_DIR = "profiles"


def _run(args, cwd=None, check=True, quiet=False):
    """Run a command, returning (rc, stdout+stderr)."""
    try:
        p = subprocess.run(args, cwd=cwd, stdout=subprocess.PIPE,
                           stderr=subprocess.STDOUT, text=True, encoding="utf-8",
                           errors="replace")
    except FileNotFoundError:
        return 127, "{} not found on PATH".format(args[0])
    out = (p.stdout or "").strip()
    if check and p.returncode != 0 and not quiet:
        pass
    return p.returncode, out


def _git(args, cwd=None, quiet=False):
    return _run(["git"] + args, cwd=cwd, quiet=quiet)


def _is_clone(d):
    return os.path.isdir(os.path.join(d, ".git"))


def _default_branch(d):
    rc, out = _git(["symbolic-ref", "--short", "HEAD"], cwd=d, quiet=True)
    if rc == 0 and out:
        return out
    return "main"


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


def assert_private(url):
    """Refuse a public repo. Returns a human note about how it was decided."""
    slug = _repo_slug(url)
    if not slug:
        return ("Could not tell whether {} is private (not a recognised GitHub URL).\n"
                "        Make sure it is private before putting a profile in it.".format(url))
    rc, out = _run(["gh", "repo", "view", slug, "--json", "visibility,isPrivate"])
    if rc != 0:
        return ("Could not verify visibility of {} ({}).\n"
                "        Make sure it is PRIVATE before putting a profile in it."
                .format(slug, out.splitlines()[0] if out else "gh unavailable"))
    try:
        info = json.loads(out)
    except Exception:
        return "Could not parse gh output while checking {}.".format(slug)
    if not info.get("isPrivate"):
        sys.exit("REFUSED: {} is {}.\n\n"
                 "A traveller profile holds dietary restrictions, home airports, health\n"
                 "constraints and travel history. It must not go in a public repo.\n"
                 "Make it private, or point this at a different repo."
                 .format(slug, info.get("visibility", "not private")))
    return "verified PRIVATE via gh: {}".format(slug)


# ── Commands ──────────────────────────────────────────────────────────────────
def cmd_setup(a):
    note = assert_private(a.url)
    cfg = store.read_config()
    cfg["profile_repo"] = a.url
    if a.dir:
        cfg["profile_repo_dir"] = os.path.abspath(os.path.expanduser(a.dir))
    path = store.write_config(cfg)
    print("Recorded profile repo in {}".format(path))
    print("  {}".format(note))
    print()
    print("On an ephemeral cloud container this config file does not survive either, so")
    print("also set this in your cloud environment:")
    print("    TRAVEL_PROFILE_REPO={}".format(a.url))
    print()
    return cmd_pull(a)


def cmd_pull(a):
    """Clone or fast-forward. Never fails the caller: a session must still work offline."""
    url = store.profile_repo()
    if not url:
        print("No profile repo configured. Run: profile_sync.py setup <private-repo-url>")
        return 0
    d = store.repo_clone_dir()
    if not _is_clone(d):
        os.makedirs(os.path.dirname(d) or ".", exist_ok=True)
        rc, out = _git(["clone", "--depth", "1", "--filter=blob:none", "--no-checkout",
                        url, d])
        if rc != 0:
            print("WARNING: could not clone the profile repo -- continuing without it.")
            print("  " + "\n  ".join(out.splitlines()[:6]))
            return 0
        _git(["sparse-checkout", "init", "--cone"], cwd=d)
        _git(["sparse-checkout", "set", SPARSE_DIR], cwd=d)
        rc, out = _git(["checkout"], cwd=d)
        if rc != 0:
            print("WARNING: sparse checkout failed -- continuing without the repo.")
            print("  " + "\n  ".join(out.splitlines()[:6]))
            return 0
        print("Cloned profile repo (shallow, sparse to {}/) -> {}".format(SPARSE_DIR, d))
    else:
        rc, out = _git(["fetch", "--depth", "1", "origin"], cwd=d)
        if rc != 0:
            print("WARNING: could not reach the profile repo -- using the local copy.")
            return 0
        dirty = _git(["status", "--porcelain"], cwd=d)[1]
        if dirty:
            print("Local profile changes not yet pushed -- NOT overwriting them:")
            for line in dirty.splitlines()[:10]:
                print("  " + line)
            print("Push them with: profile_sync.py push")
            return 0
        br = _default_branch(d)
        rc, out = _git(["reset", "--hard", "origin/" + br], cwd=d)
        if rc != 0:
            _git(["reset", "--hard", "FETCH_HEAD"], cwd=d)
        print("Profile repo up to date ({}).".format(d))

    pdir = os.path.join(d, SPARSE_DIR)
    if not os.path.isdir(pdir):
        os.makedirs(pdir, exist_ok=True)
        print("(repo has no {}/ yet -- created it; the first save will populate it)"
              .format(SPARSE_DIR))
    names = sorted(f[:-3] for f in os.listdir(pdir) if f.endswith(".md"))
    print("Profiles available from the repo: " + (", ".join(names) if names else "none yet"))
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
    print("Configured repo: " + (url or "(none)"))
    print("Config file:     " + store.config_path()
          + ("" if os.path.exists(store.config_path()) else "  (absent)"))
    print("Env override:    " + (os.environ.get("TRAVEL_PROFILE_REPO") or "(not set)"))
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
    p = sub.add_parser("setup"); p.add_argument("url"); p.add_argument("--dir")
    p.set_defaults(fn=cmd_setup)
    sub.add_parser("pull").set_defaults(fn=cmd_pull)
    p = sub.add_parser("push"); p.add_argument("-m", "--message"); p.set_defaults(fn=cmd_push)
    sub.add_parser("status").set_defaults(fn=cmd_status)
    a = ap.parse_args()
    sys.exit(a.fn(a) or 0)


if __name__ == "__main__":
    main()
