#!/usr/bin/env python3
"""
Manage traveller profiles. One markdown file per profile, YAML frontmatter for the
parts that must be machine-checked, prose for everything the planner reads.

Storage, format and resolution order all live in profile_store.py, which
skills/init/status.py imports too, so there is exactly one definition of each.

Resolution, first source that actually holds a profile wins:

    1. $TRAVEL_PROFILE_PATH            explicit override, a file or a directory
    2. a cloned private profile repo   $TRAVEL_PROFILE_REPO
    3. ~/.claude/travel/profiles       local; point at Dropbox/iCloud to sync
    4. legacy JSON, READ-ONLY          converted on read; `migrate` makes it permanent

"No profile" is never one ambiguous failure. It is either PROFILE_STORE_MISSING (no
store exists at all, so anything saved in an earlier session is gone with it) or
NO_ACTIVE_PROFILE (a store exists and is empty, so nobody has onboarded here). Both
print every path that was checked.

Commands:
    profiles.py list
    profiles.py show <name>
    profiles.py save <name>            # markdown on stdin (JSON is accepted and converted)
    profiles.py delete <name>
    profiles.py get-active             # active profile name, empty if none
    profiles.py set-active <name>
    profiles.py get-active-profile     # the active profile, or the diagnostic above
    profiles.py export [name]          # profile markdown to stdout (default: active)
    profiles.py import [name]          # profile markdown (or JSON) from stdin
    profiles.py migrate                # legacy JSON -> markdown, written for real
    profiles.py dir                    # the directory new profiles are written to
    profiles.py where                  # every candidate location and its contents
"""
import os
import sys
import re
import json
import argparse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import profile_store as store


# ── Diagnostics ───────────────────────────────────────────────────────────────
def _fail_no_profile():
    """Exit distinguishing a store that vanished from one that is merely empty, and
    name every path checked. Never a bare NO_ACTIVE_PROFILE."""
    srcs = store.sources()
    any_store = any(s.configured and s.exists for s in srcs)
    if not any_store:
        out = ["PROFILE_STORE_MISSING", "",
               "No profile store exists at all.",
               "  - On a laptop this means you have never onboarded.",
               "  - In an ephemeral cloud container it means the store was reclaimed",
               "    with an earlier session. A profile saved then is GONE: it is",
               "    deliberately never kept in the repo, so nothing restored it."]
    else:
        out = ["NO_ACTIVE_PROFILE", "",
               "A profile store exists but holds no profiles -- nobody has onboarded here."]
    out += ["", "Checked, in resolution order:"] + store.store_report() + [""]
    out += ["To restore a profile you already have:",
            "    profiles.py import < my-travel-profile.md",
            "To create a new one: run the travel-profile onboarding.",
            "New profiles are written to: " + (store.write_target().directory or "?")]
    sys.exit("\n".join(out))


def _safe(name):
    if not name or not re.fullmatch(r"[A-Za-z0-9 _-]{1,50}", name):
        sys.exit("Invalid profile name -- use letters, numbers, spaces, '_' or '-' (max 50).")
    return name


def _find(name):
    """(source, path) for a named profile, searching every source in order."""
    _safe(name)
    for s in store.sources():
        if name in s.names():
            return s, s.path_for(name)
    return None, None


def _load_named(name):
    s, path = _find(name)
    if not s:
        sys.exit("No profile named '{}'.\nKnown profiles:\n{}".format(
            name, "\n".join(store.store_report())))
    if s.fmt == "json":
        with open(path, encoding="utf-8") as f:
            p = store.migrate_json(json.load(f), name)
        p.source = s.label + " (converted on read)"
        return p
    return store.read_file(path, source=s.label)


# ── Writing ───────────────────────────────────────────────────────────────────
def _active_path(target=None):
    t = target or store.write_target()
    return os.path.join(t.directory, store.ACTIVE_FILE)


def _write(name, profile):
    """Persist immediately -- every mutation hits disk as it happens, because there is
    no reliable end-of-session to flush at."""
    target = store.write_target()
    if target.readonly:
        sys.exit("The only available store is read-only (legacy JSON). Run: profiles.py migrate")
    profile.meta["profile_name"] = name
    profile.touch()
    path = store.write_file(target.path_for(name), profile)
    # first profile in this store becomes active
    if not target.active_name() and len(target.names()) <= 1:
        with open(_active_path(target), "w", encoding="utf-8") as f:
            f.write(name)
    return path


def _read_stdin_profile(name_hint=None):
    """Markdown with frontmatter, or a v1 JSON profile, which is converted."""
    raw = sys.stdin.read()
    if not raw.strip():
        sys.exit("No input on stdin -- pipe the profile in.")
    if raw.lstrip().startswith("{"):
        try:
            obj = json.loads(raw)
        except Exception as e:
            sys.exit("Input looks like JSON but will not parse: {}".format(e))
        return store.migrate_json(obj, name_hint)
    p = store.loads(raw)
    if not p.meta:
        sys.exit("Input has no YAML frontmatter -- it does not look like a profile.\n"
                 "A profile starts with '---' on the first line. See the travel-profile skill.")
    return p


# ── Commands ──────────────────────────────────────────────────────────────────
def cmd_list(a):
    rows = [(s, s.names()) for s in store.sources()]
    if not any(names for _s, names in rows):
        print("(no profiles yet -- create one with the travel-profile onboarding)")
        print("Checked, in resolution order:")
        for line in store.store_report():
            print(line)
        return
    chosen, active = store.resolve()
    ckey = chosen.key if chosen is not None else None
    for s, names in rows:
        if not names:
            continue
        tag = " [read-only legacy]" if s.readonly else ""
        print("{}{}:".format(s.label, tag))
        for n in names:
            star = "*" if (s.key == ckey and n == active) else " "
            print("  {} {}".format(star, n))


def cmd_show(a):
    sys.stdout.write(_load_named(a.name).text())


def cmd_save(a):
    p = _read_stdin_profile(a.name)
    path = _write(_safe(a.name), p)
    print("Saved profile '{}' to {}".format(a.name, path))


def cmd_delete(a):
    s, path = _find(a.name)
    if not s:
        sys.exit("No profile named '{}'.".format(a.name))
    if s.readonly:
        sys.exit("'{}' is in the read-only legacy store ({}).\n"
                 "Delete it by hand if you mean to, or run: profiles.py migrate"
                 .format(a.name, path))
    was_active = (s.active_name() == a.name)
    os.remove(path)
    if was_active:
        remaining = s.names()
        ap = os.path.join(s.directory, store.ACTIVE_FILE)
        if remaining:
            with open(ap, "w", encoding="utf-8") as f:
                f.write(remaining[0])
            print("Deleted '{}'. Active profile is now '{}'.".format(a.name, remaining[0]))
        else:
            if os.path.exists(ap):
                os.remove(ap)
            print("Deleted '{}'. No profiles remain in {}.".format(a.name, s.label))
    else:
        print("Deleted profile '{}'.".format(a.name))


def cmd_get_active(a):
    _s, name = store.resolve()
    print(name)


def cmd_set_active(a):
    s, _path = _find(a.name)
    if not s:
        sys.exit("No profile named '{}'.".format(a.name))
    if s.readonly:
        sys.exit("'{}' is only in the read-only legacy store. Run: profiles.py migrate"
                 .format(a.name))
    with open(os.path.join(s.directory, store.ACTIVE_FILE), "w", encoding="utf-8") as f:
        f.write(_safe(a.name))
    print("Active profile set to '{}' (in {}).".format(a.name, s.label))


def cmd_get_active_profile(a):
    p = store.load_active()
    if p is None:
        _fail_no_profile()
    sys.stdout.write(p.text())


def cmd_export(a):
    if a.name:
        sys.stdout.write(_load_named(a.name).text())
        return
    p = store.load_active()
    if p is None:
        _fail_no_profile()
    sys.stdout.write(p.text())


def cmd_import(a):
    p = _read_stdin_profile(a.name)
    name = a.name or p.meta.get("profile_name") or "default"
    existed = _find(name)[0] is not None
    path = _write(_safe(name), p)
    print("{} profile '{}' at {}".format("Replaced" if existed else "Imported", name, path))
    _s, active = store.resolve()
    if active != name:
        print("(active profile is '{}' -- switch with: profiles.py set-active {})"
              .format(active or "none", name))


def cmd_migrate(a):
    """Convert every legacy JSON profile to markdown in the writable store. Never
    deletes the JSON -- it stays as a fallback until you remove it yourself."""
    legacy = [s for s in store.sources() if s.fmt == "json" and s.names()]
    if not legacy:
        print("Nothing to migrate -- no legacy JSON profiles found.")
        for line in store.store_report():
            print(line)
        return
    target = store.write_target()
    if target.readonly:
        sys.exit("No writable store available to migrate into.")
    done = []
    for s in legacy:
        for name in s.names():
            with open(s.path_for(name), encoding="utf-8") as f:
                obj = json.load(f)
            p = store.migrate_json(obj, name)
            if _find(name)[0] is not None and not a.force:
                existing, _ = _find(name)
                if existing and not existing.readonly:
                    print("skip '{}' -- already exists as markdown (use --force to overwrite)"
                          .format(name))
                    continue
            path = _write(name, p)
            done.append((name, path))
    for name, path in done:
        print("migrated '{}' -> {}".format(name, path))
    if done:
        print("\nThe legacy JSON is untouched and still readable. Remove it yourself once")
        print("you are happy with the markdown:")
        for s in legacy:
            print("    " + s.directory)


def cmd_dir(a):
    print(store.write_target().directory)


def cmd_where(a):
    print("Profile resolution ('->' is the one in use):")
    for line in store.store_report():
        print(line)
    print()
    print("New profiles are written to: " + (store.write_target().directory or "?"))
    p = store.load_active()
    if p is not None:
        print("Active profile '{}' loaded from: {}".format(p.name, p.source))


def main():
    ap = argparse.ArgumentParser(description="Manage per-user traveller profiles.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list").set_defaults(fn=cmd_list)
    p = sub.add_parser("show"); p.add_argument("name"); p.set_defaults(fn=cmd_show)
    p = sub.add_parser("save"); p.add_argument("name"); p.set_defaults(fn=cmd_save)
    p = sub.add_parser("delete"); p.add_argument("name"); p.set_defaults(fn=cmd_delete)
    sub.add_parser("get-active").set_defaults(fn=cmd_get_active)
    p = sub.add_parser("set-active"); p.add_argument("name"); p.set_defaults(fn=cmd_set_active)
    sub.add_parser("get-active-profile").set_defaults(fn=cmd_get_active_profile)
    p = sub.add_parser("export"); p.add_argument("name", nargs="?"); p.set_defaults(fn=cmd_export)
    p = sub.add_parser("import"); p.add_argument("name", nargs="?"); p.set_defaults(fn=cmd_import)
    p = sub.add_parser("migrate"); p.add_argument("--force", action="store_true")
    p.set_defaults(fn=cmd_migrate)
    sub.add_parser("dir").set_defaults(fn=cmd_dir)
    sub.add_parser("where").set_defaults(fn=cmd_where)
    a = ap.parse_args()
    a.fn(a)


if __name__ == "__main__":
    main()
