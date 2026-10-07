#!/usr/bin/env python3
"""
Traveller profile storage: markdown with YAML frontmatter.

Shared by skills/travel-profile/profiles.py and skills/init/status.py so the
resolution order and the file format are defined in exactly one place.

STDLIB ONLY, deliberately. status.py is the dependency checker -- it has to run
before anything is installed -- so this module must not import PyYAML or anything
else third-party. The frontmatter parser here handles the documented subset of
YAML only (see FORMAT below); PyYAML is used if it happens to be importable, as a
cross-check in the test path, never as a requirement.

FORMAT
    ---
    schema_version: 2
    profile_name: default
    updated: 2026-10-06
    settings:
      research_depth: light          # trailing comments are stripped
    diet:
      restriction: vegetarian
      strictness: >                  # '>' folds, '|' keeps newlines
        Free text, where the real rule gets recorded.
    budget:
      per_meal_cap: 50
      currency: USD
    mobility:
      status: none                   # none | temporary | ongoing
      review_after: null             # a date, so a temporary limit expires
    ---

    # Traveller profile -- <name>
    ## Diet
    ...prose the planner reads...

Supported: top-level scalars, one level of nesting (two-space indent), '>' and '|'
block scalars, null/~, ints, floats, true/false, single- and double-quoted strings,
and trailing '#' comments on unquoted scalars. Anything deeper is out of contract.

RESOLUTION, first source that actually holds a profile wins. Every lookup reports
which source it used; nothing resolves silently.

    1. $TRAVEL_PROFILE_PATH            explicit override, a file or a directory
    2. a cloned private profile repo   $TRAVEL_PROFILE_REPO, cloned locally
    3. ~/.claude/travel/profiles       local; point it at Dropbox/iCloud to sync
    4. legacy JSON, READ-ONLY          ~/.claude/plugins/data/travel-itinerary/profiles
"""
import os
import re
import json
import datetime

SCHEMA_VERSION = 2
ACTIVE_FILE = "_active"

# Frontmatter key order on write. Anything not listed keeps insertion order after these.
KEY_ORDER = ["schema_version", "profile_name", "updated",
             "settings", "diet", "budget", "mobility"]


# ── Frontmatter: parse ────────────────────────────────────────────────────────
def _scalar(raw):
    """One YAML scalar from the documented subset."""
    s = raw.strip()
    if s[:1] == '"' and s[-1:] == '"' and len(s) >= 2:
        return s[1:-1].replace('\\"', '"')
    if s[:1] == "'" and s[-1:] == "'" and len(s) >= 2:
        return s[1:-1].replace("''", "'")
    # a trailing comment is only a comment when unquoted and preceded by space
    m = re.search(r"\s+#", s)
    if m:
        s = s[:m.start()].strip()
    if s in ("", "null", "~"):
        return None
    if s == "true":
        return True
    if s == "false":
        return False
    if re.fullmatch(r"-?\d+", s):
        return int(s)
    if re.fullmatch(r"-?\d*\.\d+", s):
        return float(s)
    return s


def _indent(line):
    return len(line) - len(line.lstrip(" "))


def parse_frontmatter(text):
    """(meta dict, body str). No frontmatter -> ({}, text unchanged)."""
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    if not lines or lines[0].strip() != "---":
        return {}, text
    end = None
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            end = i
            break
    if end is None:
        return {}, text
    meta = _parse_block(lines[1:end])
    body = "\n".join(lines[end + 1:])
    return meta, body.lstrip("\n")


def _parse_block(lines):
    """Parse frontmatter lines into a dict, one level of nesting."""
    out = {}
    i = 0
    while i < len(lines):
        line = lines[i]
        if not line.strip() or line.lstrip().startswith("#"):
            i += 1
            continue
        if _indent(line) != 0:          # stray indent with no parent: ignore
            i += 1
            continue
        m = re.match(r"^([A-Za-z0-9_.-]+):(.*)$", line)
        if not m:
            i += 1
            continue
        key, rest = m.group(1), m.group(2)
        rest_s = rest.strip()

        if rest_s in (">", "|", ">-", "|-", ">+", "|+"):
            text, i = _read_block_scalar(lines, i + 1, rest_s)
            out[key] = text
            continue

        if rest_s == "" or rest_s.startswith("#"):
            # either a nested mapping or an empty value
            child, ni = _read_child_block(lines, i + 1)
            out[key] = child if child is not None else None
            i = ni
            continue

        out[key] = _scalar(rest)
        i += 1
    return out


def _read_block_scalar(lines, i, style):
    """Collect an indented block scalar. '>' folds to one line, '|' keeps newlines."""
    buf = []
    base = None
    while i < len(lines):
        line = lines[i]
        if line.strip() == "":
            buf.append("")
            i += 1
            continue
        ind = _indent(line)
        if base is None:
            base = ind
        if ind < base or ind == 0:
            break
        buf.append(line[base:])
        i += 1
    while buf and buf[-1] == "":
        buf.pop()
    if style.startswith(">"):
        # fold: blank lines become paragraph breaks, other newlines become spaces
        paras, cur = [], []
        for b in buf:
            if b == "":
                if cur:
                    paras.append(" ".join(cur)); cur = []
            else:
                cur.append(b.strip())
        if cur:
            paras.append(" ".join(cur))
        text = "\n\n".join(paras)
    else:
        text = "\n".join(buf)
    if style.endswith("-"):
        text = text.rstrip("\n")
    return text, i


def _read_child_block(lines, i):
    """Collect an indented child mapping. Returns (dict or None, next index)."""
    child = {}
    base = None
    while i < len(lines):
        line = lines[i]
        if not line.strip() or line.lstrip().startswith("#"):
            i += 1
            continue
        ind = _indent(line)
        if ind == 0:
            break
        if base is None:
            base = ind
        if ind < base:
            break
        m = re.match(r"^\s*([A-Za-z0-9_.-]+):(.*)$", line)
        if not m:
            i += 1
            continue
        key, rest = m.group(1), m.group(2)
        rest_s = rest.strip()
        if rest_s in (">", "|", ">-", "|-", ">+", "|+"):
            text, i = _read_block_scalar(lines, i + 1, rest_s)
            child[key] = text
            continue
        child[key] = _scalar(rest)
        i += 1
    return (child if child else None), i


# ── Frontmatter: write ────────────────────────────────────────────────────────
_PLAIN_OK = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 _.,/()&'+-]*$")


def _emit_scalar(v):
    if v is None:
        return "null"
    if v is True:
        return "true"
    if v is False:
        return "false"
    if isinstance(v, (int, float)):
        return str(v)
    s = str(v)
    if s == "":
        return '""'
    # quote anything that could be misread: leading/trailing space, ': ', ' #',
    # a YAML keyword, or a bare number
    risky = (s != s.strip() or ": " in s or s.endswith(":") or re.search(r"\s#", s)
             or s in ("null", "true", "false", "~")
             or re.fullmatch(r"-?\d+(\.\d+)?", s) or not _PLAIN_OK.match(s))
    if risky:
        return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'
    return s


def _emit_value(key, v, indent=""):
    """One frontmatter entry. Multi-line strings use a '|' literal block so a
    round-trip is exact; '>' would fold the newlines away."""
    if isinstance(v, dict):
        if not v:
            return ["{}{}:".format(indent, key)]
        out = ["{}{}:".format(indent, key)]
        for k, sub in v.items():
            out += _emit_value(k, sub, indent + "  ")
        return out
    if isinstance(v, str) and "\n" in v:
        out = ["{}{}: |".format(indent, key)]
        for line in v.split("\n"):
            out.append((indent + "  " + line).rstrip())
        return out
    return ["{}{}: {}".format(indent, key, _emit_scalar(v))]


def dump_frontmatter(meta, body):
    keys = [k for k in KEY_ORDER if k in meta] + [k for k in meta if k not in KEY_ORDER]
    lines = ["---"]
    for k in keys:
        lines += _emit_value(k, meta[k])
    lines.append("---")
    out = "\n".join(lines) + "\n"
    if body:
        out += "\n" + body.rstrip("\n") + "\n"
    return out


# ── Profile document ──────────────────────────────────────────────────────────
class Profile(object):
    def __init__(self, meta, body, source=None, path=None):
        self.meta = meta or {}
        self.body = body or ""
        self.source = source        # human label of where it came from
        self.path = path

    @property
    def name(self):
        return self.meta.get("profile_name") or (
            os.path.splitext(os.path.basename(self.path))[0] if self.path else "default")

    @property
    def research_depth(self):
        return ((self.meta.get("settings") or {}).get("research_depth") or "light")

    def text(self):
        return dump_frontmatter(self.meta, self.body)

    def touch(self):
        self.meta["schema_version"] = self.meta.get("schema_version", SCHEMA_VERSION)
        self.meta["updated"] = datetime.date.today().isoformat()


def loads(text, source=None, path=None):
    meta, body = parse_frontmatter(text)
    return Profile(meta, body, source=source, path=path)


def read_file(path, source=None):
    with open(path, encoding="utf-8") as f:
        return loads(f.read(), source=source, path=path)


def write_file(path, profile):
    """Persist immediately. Written via a temp file and replaced, so an interrupted
    write cannot truncate an existing profile."""
    d = os.path.dirname(os.path.abspath(path))
    os.makedirs(d, exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        f.write(profile.text())
    os.replace(tmp, path)
    return path


# ── Location resolution ───────────────────────────────────────────────────────
class Source(object):
    """One candidate location for profiles.

    `readonly` marks the legacy JSON store: it is still read so an existing profile
    keeps working, but nothing new is ever written there.
    """

    def __init__(self, label, directory, fmt="md", readonly=False,
                 configured=True, note="", only_file=None):
        self.label = label
        self.directory = os.path.normpath(directory) if directory else None
        self.fmt = fmt
        self.readonly = readonly
        self.configured = configured
        self.note = note
        self.only_file = only_file      # $TRAVEL_PROFILE_PATH pointing at one file

    @property
    def key(self):
        """Stable identity. sources() rebuilds its objects on every call, so anything
        comparing two sources must compare this, never object identity."""
        return (self.label, self.directory, self.only_file)

    @property
    def exists(self):
        if self.only_file:
            return os.path.isfile(self.only_file)
        return bool(self.directory) and os.path.isdir(self.directory)

    def names(self):
        if not self.configured:
            return []
        if self.only_file:
            if os.path.isfile(self.only_file):
                return [os.path.splitext(os.path.basename(self.only_file))[0]]
            return []
        if not self.exists:
            return []
        ext = "." + self.fmt
        return sorted(f[:-len(ext)] for f in os.listdir(self.directory)
                      if f.endswith(ext) and not f.startswith("_"))

    def path_for(self, name):
        if self.only_file:
            return self.only_file
        return os.path.join(self.directory, name + "." + self.fmt)

    def active_name(self):
        """The active profile here: the _active file, else the only profile."""
        names = self.names()
        if not names:
            return ""
        if self.only_file:
            return names[0]
        af = os.path.join(self.directory, ACTIVE_FILE)
        if os.path.exists(af):
            try:
                with open(af, encoding="utf-8") as f:
                    n = f.read().strip()
                if n in names:
                    return n
            except Exception:
                pass
        return names[0] if len(names) == 1 else ""

    def describe(self):
        if not self.configured:
            return "{}: not configured".format(self.label)
        where = self.only_file or self.directory
        if not self.exists:
            extra = "; " + self.note if self.note else ""
            return "{}: {}  (does not exist{})".format(self.label, where, extra)
        names = self.names()
        detail = ("{} profile(s): {}".format(len(names), ", ".join(names))
                  if names else "exists, but holds no profiles")
        if self.readonly:
            detail += "; read-only (legacy)"
        return "{}: {}  ({})".format(self.label, where, detail)


def _legacy_root():
    return (os.environ.get("CLAUDE_PLUGIN_DATA")
            or os.environ.get("TRAVEL_ITINERARY_DATA")
            or os.path.expanduser("~/.claude/plugins/data/travel-itinerary"))


def travel_dir():
    return os.path.normpath(os.path.expanduser("~/.claude/travel"))


def local_profiles_dir():
    return os.path.join(travel_dir(), "profiles")


def config_path():
    return os.path.join(travel_dir(), "config.json")


def read_config():
    """Persistent settings, so the repo URL is not retyped every session.

    On an ephemeral container this file does not survive either, which is exactly why
    $TRAVEL_PROFILE_REPO takes precedence: in the cloud it is set once as an
    environment variable and the config file is the laptop's convenience.
    """
    try:
        with open(config_path(), encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def write_config(cfg):
    os.makedirs(travel_dir(), exist_ok=True)
    tmp = config_path() + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        json.dump(cfg, f, indent=2)
    os.replace(tmp, config_path())
    return config_path()


def profile_repo():
    """The configured private profile repo URL, or ''. Env wins over the config file."""
    return (os.environ.get("TRAVEL_PROFILE_REPO")
            or read_config().get("profile_repo") or "")


def repo_clone_dir():
    return os.path.normpath(os.environ.get("TRAVEL_PROFILE_REPO_DIR")
                            or read_config().get("profile_repo_dir")
                            or os.path.join(travel_dir(), "profile-repo"))


def sources():
    """Every candidate location, in resolution order."""
    out = []

    override = os.environ.get("TRAVEL_PROFILE_PATH")
    if override:
        override = os.path.expanduser(override)
        if os.path.isdir(override) or override.endswith(("/", "\\")):
            out.append(Source("$TRAVEL_PROFILE_PATH", override))
        else:
            out.append(Source("$TRAVEL_PROFILE_PATH", os.path.dirname(override) or ".",
                              only_file=override))
    else:
        out.append(Source("$TRAVEL_PROFILE_PATH", None, configured=False))

    repo = profile_repo()
    if repo:
        out.append(Source("private profile repo",
                          os.path.join(repo_clone_dir(), "profiles"),
                          note="configured as {} -- run: profile_sync.py pull".format(repo)))
    else:
        out.append(Source("private profile repo", None, configured=False))

    out.append(Source("local", local_profiles_dir()))
    out.append(Source("legacy JSON", os.path.join(_legacy_root(), "profiles"),
                      fmt="json", readonly=True))
    return out


def resolve():
    """(source, name) of the profile to use -- the first source that actually holds one.
    (None, "") when nothing is found anywhere."""
    for s in sources():
        name = s.active_name()
        if name:
            return s, name
        found = s.names()
        if found:
            return s, found[0]
    return None, ""


def write_target():
    """Where a new or amended profile goes: the first writable source. Prefers the
    private repo when one is configured, so a save is shared by construction."""
    for s in sources():
        if s.configured and not s.readonly:
            return s
    return Source("local", local_profiles_dir())


def store_report():
    """One line per candidate location, '->' marking the one in use."""
    chosen, _name = resolve()
    ckey = chosen.key if chosen is not None else None
    return [("  -> " if s.key == ckey else "     ") + s.describe() for s in sources()]


def load_active():
    """The active Profile, or None. Legacy JSON is converted on read, never on disk."""
    s, name = resolve()
    if not s or not name:
        return None
    path = s.path_for(name)
    if s.fmt == "json":
        with open(path, encoding="utf-8") as f:
            p = migrate_json(json.load(f), name)
        p.source = s.label + " (converted on read)"
        p.path = path
        return p
    return read_file(path, source=s.label)


# ── Migration from the v1 JSON profile ────────────────────────────────────────
# JSON key -> body heading. Order here is the order of the generated document.
_SECTIONS = [
    ("dietary_restrictions", "Diet"),
    ("dietary_preferences", "Food preferences"),
    ("photography", "Photography"),
    ("activities", "Activities"),
    ("pace", "Pace"),
    ("flights", "Flights"),
    ("lodging_structure", "Lodging format"),
]

_DIET_LABELS = ["lacto-ovo-vegetarian", "lacto-vegetarian", "ovo-vegetarian",
                "pescatarian", "vegetarian", "vegan", "halal", "kosher",
                "gluten-free", "no restrictions", "none"]


def _diet_label(prose):
    """Best-effort short label. The prose always survives in diet.strictness, so a miss
    here loses nothing -- it only means the label is less specific."""
    low = (prose or "").lower()
    for lab in _DIET_LABELS:
        if lab in low:
            return "none" if lab == "no restrictions" else lab
    return "see strictness" if prose else "none"


def migrate_json(obj, name=None):
    """A v1 JSON profile -> a v2 markdown Profile, with no field loss: every value lands
    in frontmatter or in the body, and anything unrecognised is appended under
    'Other recorded preferences' rather than dropped."""
    fixed = dict(obj.get("fixed_preferences") or {})
    name = name or obj.get("profile_name") or "default"

    diet_prose = fixed.get("dietary_restrictions", "")
    meta = {
        "schema_version": SCHEMA_VERSION,
        "profile_name": name,
        "updated": datetime.date.today().isoformat(),
    }
    if obj.get("settings"):
        meta["settings"] = dict(obj["settings"])
    meta["diet"] = {"restriction": _diet_label(diet_prose)}
    if diet_prose:
        meta["diet"]["strictness"] = diet_prose
    # per_meal_cap stays null: v1 has no number, and inventing one is exactly the
    # planning error the field exists to prevent.
    meta["budget"] = {"per_meal_cap": None, "currency": None, "tier": None}
    meta["mobility"] = {"status": "none", "review_after": None}

    body = ["# Traveller profile -- {}".format(name), ""]
    used = set()
    for key, heading in _SECTIONS:
        val = fixed.get(key)
        if val:
            used.add(key)
            body += ["## {}".format(heading), "", str(val), ""]

    body += ["## Mobility", "",
             "None recorded. Set `mobility.status` and a `review_after` date if a "
             "temporary constraint applies, so it expires instead of quietly becoming "
             "permanent.", ""]

    ask = obj.get("ask_per_trip") or {}
    framework = obj.get("lodging_style_framework") or {}
    if ask or framework:
        body += ["## Ask per trip", ""]
        for k, v in ask.items():
            body.append("- **{}** -- {}".format(k.lstrip("_").replace("_", " "), v))
        if framework:
            body += ["", "Lodging style framework:"]
            for k, v in framework.items():
                body.append("- **{}** -- {}".format(k.replace("_", " "), v))
        body.append("")

    body += ["## Trip log", "",
             "_Three lines per trip: where, when, what worked. This is what makes the "
             "profile compound rather than merely persist, and it stops a future session "
             "pitching somewhere already done._", ""]

    leftovers = [(k, v) for k, v in fixed.items() if k not in used and v]
    extras = [(k, v) for k, v in obj.items()
              if k not in ("fixed_preferences", "ask_per_trip", "lodging_style_framework",
                           "settings", "profile_name") and v]
    if leftovers or extras:
        body += ["## Other recorded preferences", ""]
        for k, v in leftovers + extras:
            body.append("- **{}** -- {}".format(k.lstrip("_").replace("_", " "), v))
        body.append("")

    return Profile(meta, "\n".join(body).rstrip("\n") + "\n")
