#!/usr/bin/env python3
"""
Download the Natural Earth shapefiles the map engine needs into the per-user data dir.

Idempotent — only fetches layers that are missing. Standard library only
(urllib + zipfile), so it runs before any third-party deps are guaranteed.

Data is public domain (Natural Earth). Run once on first use; subsequent builds
are fully offline.

    python fetch_data.py            # download into the default per-user data dir
    python fetch_data.py <dir>      # download into <dir>/... explicitly
"""
import os
import sys
import io
import zipfile
import shutil
import urllib.request

BASE = "https://naciscdn.org/naturalearth/10m"

# Only the layers build_itinerary.py actually reads.
LAYERS = {
    "ne_10m_coastline": "physical",
    "ne_10m_ocean": "physical",
    "ne_10m_lakes": "physical",
    "ne_10m_rivers_lake_centerlines": "physical",
    "ne_10m_admin_1_states_provinces": "cultural",
}


def default_ne_dir():
    root = (os.environ.get("CLAUDE_PLUGIN_DATA")
            or os.environ.get("TRAVEL_ITINERARY_DATA")
            or os.path.expanduser("~/.claude/plugins/data/travel-itinerary"))
    return os.path.join(root, "natural_earth")


def _have(ne_dir, name):
    return os.path.exists(os.path.join(ne_dir, name, name + ".shp"))


def _extract(buf, dest):
    """Extract a Natural Earth zip into dest/, flattening any nested folder so the
    .shp sits directly in dest (some ND packagings nest, most don't)."""
    os.makedirs(dest, exist_ok=True)
    with zipfile.ZipFile(io.BytesIO(buf)) as z:
        z.extractall(dest)
    # flatten if the shapefile landed in a subdirectory
    base = os.path.basename(dest)
    if not os.path.exists(os.path.join(dest, base + ".shp")):
        for root, _dirs, files in os.walk(dest):
            if any(f.endswith(".shp") for f in files):
                for f in files:
                    src = os.path.join(root, f)
                    if src != os.path.join(dest, f):
                        shutil.move(src, os.path.join(dest, f))
                break


def ensure(ne_dir=None, progress=True):
    """Ensure all required layers exist in ne_dir; download the missing ones."""
    ne_dir = ne_dir or default_ne_dir()
    missing = [n for n in LAYERS if not _have(ne_dir, n)]
    if not missing:
        return ne_dir
    os.makedirs(ne_dir, exist_ok=True)
    for name in missing:
        url = "{}/{}/{}.zip".format(BASE, LAYERS[name], name)
        if progress:
            print("[travel-itinerary] downloading map layer: {} ...".format(name), file=sys.stderr)
        with urllib.request.urlopen(url, timeout=180) as r:
            buf = r.read()
        _extract(buf, os.path.join(ne_dir, name))
        if not _have(ne_dir, name):
            raise RuntimeError("downloaded {} but {}.shp is missing after extract".format(name, name))
    if progress:
        print("[travel-itinerary] map data ready at {}".format(ne_dir), file=sys.stderr)
    return ne_dir


if __name__ == "__main__":
    target = os.path.join(sys.argv[1], "natural_earth") if len(sys.argv) > 1 else None
    ensure(target)
