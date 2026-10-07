#!/usr/bin/env python3
"""
Download the Natural Earth shapefiles the map engine needs into the per-user data dir.

Idempotent — only fetches layers that are missing. Standard library only
(urllib + zipfile), so it runs before any third-party deps are guaranteed.

Data is public domain (Natural Earth). Run once on first use; subsequent builds
are fully offline.

MIRRORS. The Natural Earth CDN is the first choice: it serves one zip per layer,
so it is a single request and the smallest transfer. In a sandboxed cloud session
that host can be blocked by egress policy — observed failing with
`URLError: Tunnel connection failed: 403 Forbidden`, which left the engine unable
to render a map at all. So every layer falls back to Natural Earth's own GitHub
repository, which is the canonical upstream for the vector data.

The two mirrors are NOT interchangeable base URLs. The CDN serves a `.zip`; GitHub
serves the loose sidecar files, uncompressed, which means several requests and a
noticeably bigger transfer for the same layer (the states/provinces `.shp` alone is
~21 MB raw against ~3 MB zipped). Each mirror therefore has its own fetch strategy,
and the CDN is tried first for a reason.

    python fetch_data.py            # download into the default per-user data dir
    python fetch_data.py <dir>      # download into <dir>/... explicitly
    python fetch_data.py --check    # report what is cached, download nothing
"""
import os
import sys
import io
import zipfile
import shutil
import urllib.request
import urllib.error

# Only the layers build_itinerary.py actually reads.
LAYERS = {
    "ne_10m_coastline": "physical",
    "ne_10m_ocean": "physical",
    "ne_10m_lakes": "physical",
    "ne_10m_rivers_lake_centerlines": "physical",
    "ne_10m_admin_1_states_provinces": "cultural",
}

# Tried in order. 'zip' = one archive per layer; 'files' = loose sidecars.
MIRRORS = [
    {
        "name": "naciscdn.org",
        "kind": "zip",
        "url": "https://naciscdn.org/naturalearth/10m/{category}/{name}.zip",
    },
    {
        "name": "raw.githubusercontent.com (nvkelso/natural-earth-vector)",
        "kind": "files",
        "url": "https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master"
               "/10m_{category}/{name}.{ext}",
    },
]

# A shapefile is unusable without these; .cpg is an encoding hint and often absent,
# so a missing .cpg must not fail the layer.
REQUIRED_EXTS = ("shp", "shx", "dbf", "prj")
OPTIONAL_EXTS = ("cpg",)

TIMEOUT = 180


def default_ne_dir():
    root = (os.environ.get("CLAUDE_PLUGIN_DATA")
            or os.environ.get("TRAVEL_ITINERARY_DATA")
            or os.path.expanduser("~/.claude/plugins/data/travel-itinerary"))
    return os.path.join(root, "natural_earth")


def _have(ne_dir, name):
    return os.path.exists(os.path.join(ne_dir, name, name + ".shp"))


def _get(url):
    with urllib.request.urlopen(url, timeout=TIMEOUT) as r:
        return r.read()


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


def _fetch_zip(mirror, name, category, dest):
    url = mirror["url"].format(category=category, name=name)
    _extract(_get(url), dest)


def _fetch_files(mirror, name, category, dest):
    """Fetch the sidecars individually. Written to a staging dir and moved into place
    only once every required part arrived, so a mirror that dies halfway cannot leave
    a half-written layer that later looks cached."""
    staging = dest + ".part"
    if os.path.isdir(staging):
        shutil.rmtree(staging, ignore_errors=True)
    os.makedirs(staging, exist_ok=True)
    try:
        for ext in REQUIRED_EXTS:
            url = mirror["url"].format(category=category, name=name, ext=ext)
            with open(os.path.join(staging, name + "." + ext), "wb") as f:
                f.write(_get(url))
        for ext in OPTIONAL_EXTS:
            url = mirror["url"].format(category=category, name=name, ext=ext)
            try:
                buf = _get(url)
            except Exception:
                continue        # genuinely optional
            with open(os.path.join(staging, name + "." + ext), "wb") as f:
                f.write(buf)
        os.makedirs(dest, exist_ok=True)
        for f in os.listdir(staging):
            shutil.move(os.path.join(staging, f), os.path.join(dest, f))
    finally:
        shutil.rmtree(staging, ignore_errors=True)


_FETCHERS = {"zip": _fetch_zip, "files": _fetch_files}


def _why(exc):
    """A one-line reason a mirror failed, kept short enough to print per host."""
    if isinstance(exc, urllib.error.HTTPError):
        return "HTTP {} {}".format(exc.code, exc.reason)
    if isinstance(exc, urllib.error.URLError):
        return "unreachable: {}".format(exc.reason)
    return "{}: {}".format(type(exc).__name__, exc)


def fetch_layer(ne_dir, name, category, progress=True):
    """Try each mirror in turn. Returns the mirror name that worked.
    Raises RuntimeError naming every host tried, and why, only if all of them fail."""
    dest = os.path.join(ne_dir, name)
    failures = []
    for mirror in MIRRORS:
        try:
            if progress:
                print("[travel-itinerary] {} <- {}".format(name, mirror["name"]),
                      file=sys.stderr)
            _FETCHERS[mirror["kind"]](mirror, name, category, dest)
            if not _have(ne_dir, name):
                raise RuntimeError("fetched but {}.shp is missing after extract".format(name))
            return mirror["name"]
        except Exception as e:
            failures.append((mirror["name"], _why(e)))
            if progress:
                print("[travel-itinerary]   {} failed -- {}".format(
                    mirror["name"], failures[-1][1]), file=sys.stderr)
            shutil.rmtree(dest, ignore_errors=True)
    raise RuntimeError(_blocked_message(name, failures))


def _blocked_message(name, failures):
    """Say which hosts were blocked and what to do, rather than a stack trace."""
    lines = ["could not download map layer '{}' from any mirror:".format(name)]
    for host, why in failures:
        lines.append("    {}  --  {}".format(host, why))
    lines += [
        "",
        "    This usually means the sandbox's egress policy blocks these hosts.",
        "    The map is the only part of the itinerary that needs them; everything",
        "    else builds offline.",
        "",
        "    Options:",
        "      - allow one of the hosts above, then re-run:",
        "          python3 fetch_data.py",
        "      - or copy an existing cache from a machine that has one:",
        "          <data dir>/natural_earth/   (about 67 MB)",
        "      - find the data dir with:",
        "          python3 skills/init/status.py",
    ]
    return "\n".join(lines)


def ensure(ne_dir=None, progress=True):
    """Ensure all required layers exist in ne_dir; download the missing ones."""
    ne_dir = ne_dir or default_ne_dir()
    missing = [n for n in LAYERS if not _have(ne_dir, n)]
    if not missing:
        return ne_dir
    os.makedirs(ne_dir, exist_ok=True)
    used = set()
    for name in missing:
        used.add(fetch_layer(ne_dir, name, LAYERS[name], progress=progress))
    if progress:
        print("[travel-itinerary] map data ready at {} (via {})".format(
            ne_dir, ", ".join(sorted(used))), file=sys.stderr)
    return ne_dir


def check(ne_dir=None):
    """Report what is cached without downloading. Returns True when complete."""
    ne_dir = ne_dir or default_ne_dir()
    have = [n for n in LAYERS if _have(ne_dir, n)]
    missing = [n for n in LAYERS if not _have(ne_dir, n)]
    print("map cache: {}".format(ne_dir))
    for n in sorted(have):
        print("  cached   {}".format(n))
    for n in sorted(missing):
        print("  MISSING  {}".format(n))
    print("{}/{} layers present".format(len(have), len(LAYERS)))
    return not missing


if __name__ == "__main__":
    args = [a for a in sys.argv[1:]]
    if "--check" in args:
        args.remove("--check")
        target = os.path.join(args[0], "natural_earth") if args else None
        sys.exit(0 if check(target) else 1)
    target = os.path.join(args[0], "natural_earth") if args else None
    try:
        ensure(target)
    except RuntimeError as e:
        sys.exit("[travel-itinerary] " + str(e))
