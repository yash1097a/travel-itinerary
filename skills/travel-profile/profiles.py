#!/usr/bin/env python3
"""
Manage traveller profiles, stored PER-USER outside the plugin repo.

Location: $CLAUDE_PLUGIN_DATA/profiles/  (falls back to
$TRAVEL_ITINERARY_DATA or ~/.claude/plugins/data/travel-itinerary/profiles/).
Profiles survive plugin updates and are never committed anywhere.

Commands:
    profiles.py list
    profiles.py show <name>
    profiles.py save <name>            # reads profile JSON from stdin, validates, writes
    profiles.py delete <name>
    profiles.py get-active             # prints active profile name (empty if none)
    profiles.py set-active <name>
    profiles.py get-active-profile     # prints active profile JSON, or exits NO_ACTIVE_PROFILE
    profiles.py dir                    # prints the profiles directory
"""
import os
import sys
import re
import json
import argparse

HERE = os.path.dirname(os.path.abspath(__file__))


def data_root():
    return (os.environ.get("CLAUDE_PLUGIN_DATA")
            or os.environ.get("TRAVEL_ITINERARY_DATA")
            or os.path.expanduser("~/.claude/plugins/data/travel-itinerary"))


def profiles_dir():
    d = os.path.join(data_root(), "profiles")
    os.makedirs(d, exist_ok=True)
    return d


def _active_file():
    return os.path.join(profiles_dir(), "_active")


def _safe(name):
    if not name or not re.fullmatch(r"[A-Za-z0-9 _-]{1,50}", name):
        sys.exit("Invalid profile name — use letters, numbers, spaces, '_' or '-' (max 50).")
    return name


def _path(name):
    return os.path.join(profiles_dir(), _safe(name) + ".json")


def _active_name():
    f = _active_file()
    name = open(f, encoding="utf-8").read().strip() if os.path.exists(f) else ""
    if name and not os.path.exists(_path(name)):
        name = ""
    return name


def _validate(obj):
    try:
        from jsonschema import Draft202012Validator
    except Exception:
        return  # validation is best-effort
    schema = json.load(open(os.path.join(HERE, "profile.schema.json"), encoding="utf-8"))
    errs = sorted(Draft202012Validator(schema).iter_errors(obj), key=lambda e: list(e.path))
    if errs:
        msg = "\n".join("  - {}: {}".format("/".join(map(str, e.path)) or "(root)", e.message)
                        for e in errs[:20])
        sys.exit("Profile failed validation:\n" + msg)


def cmd_list(a):
    names = sorted(f[:-5] for f in os.listdir(profiles_dir()) if f.endswith(".json"))
    if not names:
        print("(no profiles yet — create one with the travel-profile onboarding)")
        return
    active = _active_name()
    for n in names:
        print(("* " if n == active else "  ") + n)


def cmd_show(a):
    p = _path(a.name)
    if not os.path.exists(p):
        sys.exit("No profile named '{}'.".format(a.name))
    sys.stdout.write(open(p, encoding="utf-8").read())


def cmd_save(a):
    raw = sys.stdin.read()
    try:
        obj = json.loads(raw)
    except Exception as e:
        sys.exit("Input is not valid JSON: {}".format(e))
    obj.setdefault("profile_name", a.name)
    _validate(obj)
    with open(_path(a.name), "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=2, ensure_ascii=False)
    if not _active_name():  # first profile becomes active
        open(_active_file(), "w", encoding="utf-8").write(a.name)
    print("Saved profile '{}' to {}".format(a.name, profiles_dir()))


def cmd_delete(a):
    p = _path(a.name)
    if not os.path.exists(p):
        sys.exit("No profile named '{}'.".format(a.name))
    was_active = (_active_name() == a.name)
    os.remove(p)
    if was_active:
        remaining = sorted(f[:-5] for f in os.listdir(profiles_dir()) if f.endswith(".json"))
        if remaining:
            open(_active_file(), "w", encoding="utf-8").write(remaining[0])
            print("Deleted '{}'. Active profile is now '{}'.".format(a.name, remaining[0]))
        else:
            if os.path.exists(_active_file()):
                os.remove(_active_file())
            print("Deleted '{}'. No profiles remain.".format(a.name))
    else:
        print("Deleted profile '{}'.".format(a.name))


def cmd_get_active(a):
    print(_active_name())


def cmd_set_active(a):
    if not os.path.exists(_path(a.name)):
        sys.exit("No profile named '{}'.".format(a.name))
    open(_active_file(), "w", encoding="utf-8").write(_safe(a.name))
    print("Active profile set to '{}'.".format(a.name))


def cmd_get_active_profile(a):
    name = _active_name()
    if not name:
        sys.exit("NO_ACTIVE_PROFILE")
    sys.stdout.write(open(_path(name), encoding="utf-8").read())


def cmd_dir(a):
    print(profiles_dir())


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
    sub.add_parser("dir").set_defaults(fn=cmd_dir)
    a = ap.parse_args()
    a.fn(a)


if __name__ == "__main__":
    main()
