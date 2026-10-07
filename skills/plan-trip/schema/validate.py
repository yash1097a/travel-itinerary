"""
Validate an itinerary JSON instance against itinerary.schema.json, then run the
cross-checks the schema cannot express.

The schema catches a malformed document. The cross-checks catch a document that is
well-formed and still wrong -- the failures that actually reached finished PDFs:

  ERROR    a day schedules a restaurant on a weekday it is closed. A real itinerary
           booked a headline dinner on the one night of the week the place was shut,
           and nothing caught it.
  WARNING  a dining entry named on a day does not appear in the `dining` shortlist
           (a day may legitimately name a market stall, so this is not fatal)
  WARNING  one cuisine dominates the dinner slots -- the same cuisine in three of
           four dinners, invisible when dining is only ever seen a day at a time
  WARNING  an entry with no `why` or no `dishes`, which are what make the page worth
           printing

Usage:
    python validate.py                 # validates pnw_example.json
    python validate.py path/to/trip.json
"""
import json
import os
import sys
import datetime
from jsonschema import Draft202012Validator

HERE = os.path.dirname(os.path.abspath(__file__))
SCHEMA = os.path.join(HERE, "itinerary.schema.json")

WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
DINNER_SHARE_LIMIT = 0.5


def load(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


# ── Cross-checks ──────────────────────────────────────────────────────────────
def _norm(s):
    return " ".join((s or "").split()).casefold()


def _day_weekday(day):
    """The weekday for a day entry, from `date` or `weekday`, else None. A trip with
    neither is simply not checked for closures -- absence is not an error."""
    d = day.get("date")
    if d:
        try:
            return WEEKDAYS[datetime.date.fromisoformat(d).weekday()]
        except Exception:
            return None
    return day.get("weekday") or None


def _dining_index(itin):
    """{normalised name: entry} over every dining entry."""
    idx = {}
    for group in (itin.get("dining") or {}).get("groups", []):
        for e in group.get("entries", []):
            idx[_norm(e.get("name"))] = e
    return idx


def _match(place, index):
    """Resolve a day's `place` to a dining entry. Returns (entry, how) or (None, None).

    Exact first. A substring match is reported as such, because it is the looser
    rule and a reader should know which one fired.
    """
    key = _norm(place)
    if key in index:
        return index[key], "exact"
    for name, entry in index.items():
        if name and (name in key or key in name):
            return entry, "matched '{}'".format(entry.get("name"))
    return None, None


def cross_checks(itin):
    """(errors, warnings) as lists of strings. Safe to call on any valid instance."""
    errors, warnings = [], []
    dining = itin.get("dining") or {}
    index = _dining_index(itin)
    days = itin.get("days") or []

    # --- entry quality, and duplicate names that would make matching ambiguous
    seen = {}
    for group in dining.get("groups", []):
        for e in group.get("entries", []):
            name = e.get("name", "?")
            key = _norm(name)
            if key in seen:
                warnings.append(
                    "dining: two entries named '{}' -- a day naming it cannot be resolved "
                    "to one of them".format(name))
            seen[key] = True
            if not e.get("why"):
                warnings.append("dining: '{}' has no 'why' -- the page is just a list "
                                "without it".format(name))
            if not e.get("dishes"):
                warnings.append("dining: '{}' has no 'dishes'".format(name))
            if e.get("hours") and not e.get("closed"):
                low = _norm(e["hours"])
                if "closed" in low or "except" in low:
                    warnings.append(
                        "dining: '{}' mentions a closure inside 'hours' but has no 'closed' "
                        "array -- prose there cannot be checked against the schedule"
                        .format(name))

    # --- day picks: resolvable, and not scheduled on a closed day
    dinner_cuisines = []
    unresolved = []
    for i, day in enumerate(days, start=1):
        wd = _day_weekday(day)
        for row in day.get("where_to_eat") or []:
            place = row.get("place", "")
            cat = _norm(row.get("category"))
            entry, how = _match(place, index) if index else (None, None)

            if index and entry is None:
                unresolved.append("day {}: '{}' ({})".format(
                    i, place, row.get("category", "?")))

            if entry is not None and wd:
                closed = entry.get("closed") or []
                if wd in closed:
                    errors.append(
                        "day {} is a {} and schedules '{}' for {}, but it is closed {} "
                        "({})".format(i, wd, place, row.get("category", "?"),
                                      "/".join(closed), how))

            if entry is not None and "dinner" in cat:
                dinner_cuisines.append(_norm(entry.get("cuisine")) or "?")

    # Aggregated, not one line each: a partly-filled dining block otherwise buries the
    # errors under a dozen identical warnings.
    if unresolved:
        shown = unresolved[:5]
        more = len(unresolved) - len(shown)
        warnings.append(
            "{} day pick(s) are not in the dining shortlist -- fine for a market stall or a "
            "lodge restaurant, otherwise add them: {}{}".format(
                len(unresolved), "; ".join(shown),
                " ... and {} more".format(more) if more else ""))

    # --- cuisine balance across dinners
    if len(dinner_cuisines) >= 3:
        for cuisine in sorted(set(dinner_cuisines)):
            n = dinner_cuisines.count(cuisine)
            share = n / float(len(dinner_cuisines))
            if share > DINNER_SHARE_LIMIT:
                warnings.append(
                    "cuisine balance: {} is {} of {} dinner slots ({:.0f}%) -- vary it or "
                    "say why".format(cuisine, n, len(dinner_cuisines), share * 100))

    # --- a closed array that can never be checked
    if dining and any((e.get("closed") for g in dining.get("groups", [])
                       for e in g.get("entries", []))):
        if not any(_day_weekday(d) for d in days):
            warnings.append(
                "dining entries list closures but no day has a 'date' or 'weekday', so the "
                "closed-day check cannot run -- add dates to days[] to enable it")

    return errors, warnings


# ── Entry point ───────────────────────────────────────────────────────────────
def main(instance_path):
    schema = load(SCHEMA)
    instance = load(instance_path)

    Draft202012Validator.check_schema(schema)  # the schema itself is valid
    validator = Draft202012Validator(schema)
    errors = sorted(validator.iter_errors(instance), key=lambda e: list(e.path))

    name = os.path.basename(instance_path)
    if errors:
        print("INVALID  {}  ({} schema error(s)):".format(name, len(errors)))
        for e in errors:
            loc = "/".join(str(p) for p in e.path) or "(root)"
            print("  - at {}: {}".format(loc, e.message))
        return 1

    xerrors, warnings = cross_checks(instance)
    nd = len(instance.get("days", []))
    ns = len(instance.get("map", {}).get("stops", []))
    ne = sum(len(g.get("entries", []))
             for g in (instance.get("dining") or {}).get("groups", []))
    summary = "{} day pages, {} map stops{}".format(
        nd, ns, ", {} dining entries".format(ne) if ne else "")

    for w in warnings:
        print("  warning: " + w)

    if xerrors:
        print("INVALID  {}  ({})".format(name, summary))
        print("  {} cross-check error(s) -- these would ship a wrong itinerary:"
              .format(len(xerrors)))
        for e in xerrors:
            print("  - " + e)
        return 1

    print("VALID  {}  ({}){}".format(
        name, summary, "  [{} warning(s)]".format(len(warnings)) if warnings else ""))
    return 0


if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else os.path.join(HERE, "pnw_example.json")
    sys.exit(main(target))
