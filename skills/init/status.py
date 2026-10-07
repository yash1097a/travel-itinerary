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

# Profile storage lives in the travel-profile skill, so the format and the resolution
# order have exactly one definition. That module is stdlib-only for this reason: this
# script is the dependency checker and has to run before anything is installed.
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                os.pardir, "travel-profile"))
try:
    import profile_store as store
except Exception:
    store = None

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
    """(names, active, source label). Covers every candidate location, including the
    private repo clone and the read-only legacy JSON store."""
    if store is None:            # degraded: report nothing rather than guess
        return [], "", ""
    names = []
    for s in store.sources():
        for n in s.names():
            if n not in names:
                names.append(n)
    src, active = store.resolve()
    return sorted(names), active, (src.label if src else "")


def map_cached(root):
    ne = os.path.join(root, "natural_earth")
    return all(os.path.exists(os.path.join(ne, l, l + ".shp")) for l in MAP_LAYERS)


def research_depth(root, active):
    """settings.research_depth from the active profile (default 'light')."""
    if not active or store is None:
        return None
    try:
        p = store.load_active()
        return p.research_depth if p is not None else "light"
    except Exception:
        return "light"


def main():
    root = data_root()
    miss = missing_deps()
    names, active, source = profiles_state(root)
    cached = map_cached(root)

    print("Travel Itinerary - status")
    print("  Dependencies: " + ("OK" if not miss else "MISSING (" + ", ".join(miss) + ")"))
    depth = research_depth(root, active)
    if names:
        print("  Profiles: {} ({})".format(len(names), ", ".join(names)))
        print("  Active profile: " + (active or "none set")
              + (" [from {}]".format(source) if source else ""))
        if depth:
            print("  Research depth: " + depth)
    else:
        print("  Profiles: none yet")
        # Say where we looked. An empty report is how a reclaimed container looks, and
        # it must not be mistaken for a user who has never onboarded.
        if store is not None:
            for line in store.store_report():
                print("   " + line)
    print("  Map data: " + ("cached (offline-ready)" if cached
                            else "not yet - downloads automatically on your first trip"))
    print("  Data dir: " + root)
    print("STATUS_JSON=" + json.dumps({
        "deps_missing": miss, "profiles": names, "active": active,
        "profile_source": source, "research_depth": depth,
        "map_cached": cached, "data_dir": root,
    }))


if __name__ == "__main__":
    main()
