# STYLE.md — Visual Specification

The build script (`build_itinerary.py`) **is** the template — this file is the concise
visual spec so the look survives even if the script is ever regenerated. It describes the
**current** design system exactly. Where this document and an older description disagree,
**this document wins** (see *Deliberately removed / rejected* at the end — do not
reintroduce those).

---

## Palette

| Token | Hex | Where it's used |
|---|---|---|
| **Forest green** | `#1E3D2F` | Cover top band; body-page header bar; day-header band; section-badge box; table header rows (Where to Stay, Where to Eat, Worth Knowing); activity pills; serif headings; cover date; tile values; highlight names |
| **Gold** | `#C4973A` | All accents — rules, section labels, "DAY N", tile top-strips, timeline spine + node rings, gold underline, map route line, contour motif, cover subtitle, cover date-block rules, timeline time labels |
| **Sage** | `#EDF3F0` | Stat tiles; alternating table row shade; info-table label column; highlight-card fill; cover kicker/waypoints text; running-header text |
| **Cream** | `#F6F5F0` | Alternating row shade in Worth-Knowing / info tables |
| **Teal** | `#2A5C52` | **Text accent only** — the small category labels (COFFEE / LUNCH / DINNER) and Worth-Knowing place names, plus the dining category icon. *Not* used as a header/panel background. |
| **Dark / Med / Pale** | `#2B2B2B` / `#555555` / `#999999` | Body / secondary / footnote text |
| **Rule** | `#D0D4CC` | Table gridlines and box borders |

**Map colours (matplotlib):** land `#F4F2EA`, water `#DCE8E4`, muted border `#8AA394`,
paper `#FBF8F1`, plus green route/coast and gold route line.

---

## Typography

Two families only — **EB Garamond** (bundled OFL, `assets/fonts/EBGaramond-Var.ttf`,
registered as `Garamond`) for serif **display**, and **Helvetica** for everything else.

- **Serif (EB Garamond):** cover title (46 pt), cover subtitle (17 pt gold), cover date
  (24 pt green), section headings (20 pt green — e.g. "Your Route", "What to Bring"),
  day-page titles (19 pt white in the header band). Titles are set in **title case**, not
  uppercased.
- **Helvetica / Helvetica-Bold:** body copy, all labels, tables, the timeline, tiles,
  pills, badges, headers/footers. Section *labels* are letter-spaced, uppercased, gold.

**Letter-spacing gotcha (hard-won):** the `spaced()` helper joins letters with regular
spaces but separates words with **non-breaking spaces** — because ReportLab's Paragraph
parser collapses runs of ordinary spaces, which would merge the words. Do not "simplify"
this back to plain spaces.

---

## Iconography

Small **Tabler line icons** (MIT, `assets/icons/`, SVG via `svglib`), recoloured in-palette,
single stroke weight, **used as restrained accents only** — never multicolour, never one
on every row. Icons are chosen by a **category → icon lookup with a neutral fallback**
(`mountain`), so content stays generic: a "Coffee" row shows a cup because the data says
"Coffee", not because coffee is a fixed slot.

Icon placements: dining categories (coffee/utensils/glass), the Where-to-Eat and
Worth-Knowing header tabs, the four planning-section labels (plane/car/bed/checklist),
activity pills, and glance tiles (thermometer/clock/road/car/mountain).

---

## Page anatomy

**Cover.** Green top band (~50% height) carrying a subtle gold **topographic-contour
motif**; centred kicker (letter-spaced), gold rule, serif title, gold serif subtitle, and
waypoints line at the band's base. Lower white area: a centred date block (gold rule →
serif date → letter-spaced duration → gold rule) above a row of sage **stat boxes**.
*No seal/monogram. No footer strip.* The cover carries no flight info.

**Summary.** `01` section badge + serif heading ("Your Route") + a **plain justified intro
paragraph** (no drop cap) → the **route map** (centred, boxed) → a **centred, bold,
underlined** "TRIP AT A GLANCE" gold label → full-width **glance tiles** (icon + value +
caption) → **centred activity pills** (green, white icon + label) → a row of **highlight
cards** (gold top-rule, green name, grey caption).

**Planning.** `02` section badge, then an ordered list of panels, each = an icon+label (or
letter-spaced label) + gold rule + a table:
- **info** panels — 2-column label/value (Flights, Getting Around, Before You Go, etc.).
- **lodging** panel — 4-column (Night(s) / Day(s) / Area & Suggested Properties / Notes).
  The area cell holds the **neighbourhood (bold green) + 2–3 suggested properties, each
  `Name — reason`**, and the Notes cell holds the rationale. Never one prescriptive hotel;
  never area-only; no prices.

Planning may **flow to a second page** for content-heavy trips — each panel is wrapped in
`KeepTogether` so subsections never split. Practical capacity ≈ **4 panels + ~5 lodging
rows** per page; beyond that, consolidate panels or accept a clean two-page Planning.

**Day page.** Green **day-header band** with a gold left-accent bar, gold "DAY N", serif
day title, and a gold subtitle note (top-right). Below it, the **vertical timeline spine**
— a gold line with green/gold node dots, gold time labels, and wrapped copy. Then two
optional blocks, both with **green** header tabs:
- **WHERE TO EAT** (fork icon) — rows of category (teal, with dining icon) + place + note.
- **WORTH KNOWING** (monument icon) — place (teal) + factual blurb.

**Packing.** Gold section label + serif heading ("What to Bring") + a 2-column table
(item / detail) + a gold rule + a centred grey footnote.

---

## The map

Coordinate-driven and **offline**: real lat/long stops plotted on bundled public-domain
**Natural Earth** shapefiles (coastline, state borders, ocean, lakes, rivers), rendered in
the palette. Gold route line through the stops in order; green/gold markers; **greedy
label de-confliction**; optional per-leg **drive-time/distance pills**; a faint lat/long
**graticule**; and a small **compass**. Handles landlocked regions (empty ocean/coast
layers are skipped, not fatal). Exported as **JPEG (quality ~87)** and embedded — this is
what keeps the whole PDF ~0.3–0.4 MB.

---

## Layout discipline (preserve)

- **One page per section** is the default: Cover, Summary, Planning, one page per day,
  Packing. Planning is the one section allowed to flow to a second page when content
  demands (subsections kept whole).
- **`KeepTogether`** wraps every table / timeline / map block so it never splits across a
  page boundary — it moves intact instead.
- **JPEG, not PNG,** for embedded imagery (the map + contour), for file size.
- **Verify by rasterising every page** after each build — confirm no overflow.

---

## Content sizing (so it renders one-page-clean)

- Lodging property **reasons ~6 words**, **notes ~1 sentence** → each property stays on one line.
- Day pages: a full timeline + optional eat/worth blocks fit one page; trim prose rather
  than overflow.
- Cover title fits at 46 pt across the width; very long titles are the only case that
  might need attention.

---

## Deliberately removed / rejected — do NOT reintroduce

These were tried or existed earlier and were intentionally taken out. A regenerated engine
must not bring them back:

- **Cover seal / compass monogram** — removed (the `_seal()` function and the
  `cover.monogram` schema field are gone).
- **Cover footer strip carrying flight info** — removed (the `cover.footer_strip` field is
  gone); flight info lives on the Planning page only.
- **Summary drop cap** (the large gold initial) — removed in favour of a plain paragraph
  (the `DropCapPara` flowable is gone).
- **Teal Where-to-Eat header tab** — changed to green for uniformity; teal survives only as
  a small text accent.
- **Extra serif faces** (Cormorant, Fraunces) — evaluated, not chosen; EB Garamond only.
- **Illustrated/hand-drawn or "fantasy" maps, watercolor art, and any photographs** —
  rejected earlier in the project. The deliverable is illustration-free **except** the
  coordinate map.
