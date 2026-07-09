#!/usr/bin/env python3
"""
Backend readiness check for the travel-itinerary plugin.

Prints a short human-readable status plus a machine-readable STATUS_JSON line the
`init` skill uses to tailor its greeting. Read-only and fast; safe to run any time.
"""
import os
import sys
import json
import importlib

# module import name -> pip package name (for a friendly "missing" message)
REQUIRED = {
    "reportlab": "reportlab", "geopandas": "geopandas", "shapely": "shapely",
    "pyogrio": "pyogrio", "matplotlib": "matplotlib", "numpy": "numpy",
    "PIL": "pillow", "svglib": "svglib", "jsonschema": "jsonschema",
}
MAP_LAYERS = ["ne_10m_coastline", "ne_10m_ocean", "ne_10m_lakes",
              "ne_10m_rivers_lake_centerlines", "ne_10m_admin_1_states_provinces"]


def data_root():
    return (os.environ.get("CLAUDE_PLUGIN_DATA")
            or os.environ.get("TRAVEL_ITINERARY_DATA")
            or os.path.expanduser("~/.claude/plugins/data/travel-itinerary"))


def missing_deps():
    missing = []
    for mod, pkg in REQUIRED.items():
        try:
            importlib.import_module(mod)
        except Exception:
            missing.append(pkg)
    return missing


def profiles_state(root):
    pdir = os.path.join(root, "profiles")
    names, active = [], ""
    if os.path.isdir(pdir):
        names = sorted(f[:-5] for f in os.listdir(pdir) if f.endswith(".json"))
        af = os.path.join(pdir, "_active")
        if os.path.exists(af):
            a = open(af, encoding="utf-8").read().strip()
            if a in names:
                active = a
    return names, active


def map_cached(root):
    ne = os.path.join(root, "natural_earth")
    return all(os.path.exists(os.path.join(ne, l, l + ".shp")) for l in MAP_LAYERS)


def main():
    root = data_root()
    miss = missing_deps()
    names, active = profiles_state(root)
    cached = map_cached(root)

    print("Travel Itinerary - status")
    print("  Dependencies: " + ("OK" if not miss else "MISSING (" + ", ".join(miss) + ")"))
    if names:
        print("  Profiles: {} ({})".format(len(names), ", ".join(names)))
        print("  Active profile: " + (active or "none set"))
    else:
        print("  Profiles: none yet")
    print("  Map data: " + ("cached (offline-ready)" if cached
                            else "not yet - downloads automatically on your first trip"))
    print("  Data dir: " + root)
    print("STATUS_JSON=" + json.dumps({
        "deps_missing": miss, "profiles": names, "active": active,
        "map_cached": cached, "data_dir": root,
    }))


if __name__ == "__main__":
    main()
