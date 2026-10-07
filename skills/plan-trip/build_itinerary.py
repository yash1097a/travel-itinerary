#!/usr/bin/env python3
"""
Schema-driven travel-itinerary PDF engine (refined design system).

Reads an itinerary JSON instance (schema/itinerary.schema.json) and emits a
multi-page PDF. Design system:
  - EB Garamond serif display (cover, section headings, day titles) + Helvetica body
  - vertical timeline spine on day pages, drop-cap intro, numbered section badges
  - restrained functional line icons (Tabler, MIT) via category->icon lookup + fallback
  - topographic contour cover motif + engraved monogram
  - coordinate-driven Natural Earth map with leg annotations, graticule, compass,
    and greedy label de-confliction
Layout discipline preserved: one page per section, KeepTogether anti-overflow,
letter-spaced labels, JPEG-embedded imagery.

Usage:
    python build_itinerary.py schema/pnw_example.json
    python build_itinerary.py trip.json --out output/Trip.pdf
"""
import os, sys, json, math, argparse

from reportlab.lib.pagesizes import letter
from reportlab.lib.units import inch
from reportlab.lib.colors import HexColor, white
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_JUSTIFY
from reportlab.platypus import (
    BaseDocTemplate, Frame, PageTemplate, NextPageTemplate,
    Paragraph, Spacer, Table, TableStyle, PageBreak, Image as RLImage, KeepTogether,
)
from reportlab.platypus.flowables import Flowable
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.graphics import renderPDF

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)  # so `import fetch_data` resolves when run from anywhere

# Per-user data dir — persists across plugin updates and is NOT part of the shipped repo.
# The Natural Earth shapefiles are downloaded here on first use (see fetch_data.py).
DATA_ROOT = (os.environ.get("CLAUDE_PLUGIN_DATA")
             or os.environ.get("TRAVEL_ITINERARY_DATA")
             or os.path.expanduser("~/.claude/plugins/data/travel-itinerary"))
NE_DIR = os.path.join(DATA_ROOT, "natural_earth")
FONT_DIR = os.path.join(HERE, "assets", "fonts")   # bundled with the plugin (read-only)
ICON_DIR = os.path.join(HERE, "assets", "icons")   # bundled with the plugin (read-only)

def _ensure_map_data():
    """Download the Natural Earth shapefiles into NE_DIR on first use (idempotent)."""
    import fetch_data
    fetch_data.ensure(NE_DIR)

# ── Palette ───────────────────────────────────────────────────────────────────
GREEN  = HexColor('#1E3D2F'); GOLD = HexColor('#C4973A'); SAGE = HexColor('#EDF3F0')
CREAM  = HexColor('#F6F5F0'); DARK = HexColor('#2B2B2B'); MED  = HexColor('#555555')
PALE   = HexColor('#999999'); RULE = HexColor('#D0D4CC'); TEAL = HexColor('#2A5C52')

MPL_GREEN='#1E3D2F'; MPL_GOLD='#C4973A'; MPL_CREAM='#FBF8F1'; MPL_LAND='#F4F2EA'
MPL_WATER='#DCE8E4'; MPL_MED='#555555'; MPL_DARK='#2B2B2B'; MPL_BORDER='#8AA394'

# ── Geometry ──────────────────────────────────────────────────────────────────
W, H = letter
LM = RM = 63
CW = W - LM - RM
HEADER_H = 28; FOOTER_H = 44
FRAME_H = H - HEADER_H - FOOTER_H - 8

# ── Fonts ─────────────────────────────────────────────────────────────────────
SERIF = "Garamond"
pdfmetrics.registerFont(TTFont(SERIF, os.path.join(FONT_DIR, "EBGaramond-Var.ttf")))

# ── Styles ────────────────────────────────────────────────────────────────────
def ps(name, fn='Helvetica', fs=9.5, ld=14, col=None, al=TA_LEFT, **kw):
    return ParagraphStyle(name, fontName=fn, fontSize=fs, leading=ld,
                          textColor=col or DARK, alignment=al, **kw)

def spaced(text):
    # letters joined by regular spaces (render); word gaps use non-breaking
    # spaces so ReportLab's Paragraph parser doesn't collapse them away.
    gap = '   '
    return gap.join(' '.join(list(w)) for w in text.split(' '))

ST = {
    'sec_lbl': ps('sl',  fn='Helvetica-Bold', fs=7, ld=9, col=GOLD, spaceBefore=8, spaceAfter=3),
    'sec_hd':  ps('sh',  fn=SERIF, fs=20, ld=22, col=GREEN, spaceAfter=6),
    'time':    ps('tm',  fn='Helvetica-Bold', fs=7.5, ld=11, col=GOLD),
    'a_title': ps('at',  fn='Helvetica-Bold', fs=9.3, ld=12.5),
    'a_body':  ps('ab',  fs=8.7, ld=12.5, col=MED, spaceAfter=2),
    'th':      ps('th',  fn='Helvetica-Bold', fs=7.3, ld=10, col=white),
    'td':      ps('td',  fs=8.3, ld=11.5),
    'tdb':     ps('tb',  fn='Helvetica-Bold', fs=8.3, ld=11.5),
    'fn':      ps('fn',  fs=7.5, ld=11, col=PALE, al=TA_CENTER),
    'eat_hd':  ps('eh',  fn='Helvetica-Bold', fs=7, ld=9, col=white),
    'eat_cat': ps('ec',  fn='Helvetica-Bold', fs=7.3, ld=10.5, col=TEAL),
    'eat_val': ps('ev',  fs=8.3, ld=11.5, col=DARK),
    'eat_note':ps('en',  fs=7.3, ld=10.5, col=MED),
    'stay_area': ps('sa', fn='Helvetica-Bold', fs=8.3, ld=11, col=GREEN),
    'stay_prop': ps('sp', fs=7.4, ld=9.4, col=DARK),
}

# ── Icons (Tabler, MIT) ───────────────────────────────────────────────────────
from svglib.svglib import svg2rlg
_ICON_CACHE = {}
def _recolor(node, color):
    for e in getattr(node, "contents", []):
        if hasattr(e, "strokeColor"):     # Tabler outline paths ship stroke=None
            e.strokeColor = color
        if hasattr(e, "contents"):
            _recolor(e, color)

def icon_drawing(name, color):
    key = (name, color.hexval())
    if key not in _ICON_CACHE:
        d = svg2rlg(os.path.join(ICON_DIR, name + ".svg"))
        _recolor(d, color)
        _ICON_CACHE[key] = d
    return _ICON_CACHE[key]

def draw_icon(canv, name, color, x, y, size):
    d = icon_drawing(name, color)
    s = size / d.width
    canv.saveState(); canv.translate(x, y); canv.scale(s, s)
    renderPDF.draw(d, canv, 0, 0); canv.restoreState()

class IconFlow(Flowable):
    def __init__(self, name, color, size=12):
        Flowable.__init__(self); self.name=name; self.color=color; self.size=size
    def wrap(self, aw, ah): return self.size, self.size
    def draw(self): draw_icon(self.canv, self.name, self.color, 0, 0, self.size)

def icon_label_cell(icon, text, color, size=12, letterspaced=True, fs=7):
    p = Paragraph(spaced(text) if letterspaced else text,
                  ParagraphStyle("il", fontName="Helvetica-Bold", fontSize=fs,
                                 leading=size+1, textColor=color))
    t = Table([[IconFlow(icon, color, size), p]], colWidths=[size+5, None])
    t.setStyle(TableStyle([('VALIGN',(0,0),(-1,-1),'MIDDLE'),
        ('LEFTPADDING',(0,0),(-1,-1),0),('RIGHTPADDING',(0,0),(-1,-1),2),
        ('TOPPADDING',(0,0),(-1,-1),0),('BOTTOMPADDING',(0,0),(-1,-1),0)]))
    return t

DINING_ICONS = {"coffee":"coffee","breakfast":"coffee","lunch":"tools-kitchen-2",
                "dinner":"tools-kitchen-2","drinks":"glass-full","dessert":"glass-full"}
ACTIVITY_ICONS = {"coastal hiking":"walk","hiking":"walk","day hikes":"walk","rainforest walks":"tree",
                  "scenic drives":"car","tide pooling":"ripple","wildlife watching":"binoculars",
                  "waterfall viewing":"droplet","photography":"camera","sunrise photography":"camera",
                  "geyser basins":"droplet","fall foliage":"tree","fall colors":"tree"}
PLANNING_ICONS = {"flights":"plane","getting around":"car","where to stay":"bed",
                  "advance bookings":"list-check","before you go":"list-check",
                  "park access & safety":"list-check"}
# Cuisine -> icon. A dict, NOT a filesystem lookup: icon_drawing() raises on a missing
# file, and there is no per-cuisine art bundled. Anything unmapped gets the neutral fork
# and knife, which is the honest answer for 'Mexican' or 'Thai'.
CUISINE_ICONS = {"coffee":"coffee","cafe":"coffee","café":"coffee","bakery":"coffee",
                 "pastry":"coffee","tea":"coffee","bar":"glass-full","wine":"glass-full",
                 "brewery":"glass-full","cocktails":"glass-full","drinks":"glass-full",
                 "dessert":"glass-full","ice cream":"glass-full"}
def cuisine_icon(cuisine): return CUISINE_ICONS.get((cuisine or "").strip().lower(),
                                                    "tools-kitchen-2")
def dining_icon(cat): return DINING_ICONS.get(cat.strip().lower(), "tools-kitchen-2")
def activity_icon(tag): return ACTIVITY_ICONS.get(tag.strip().lower(), "mountain")
def planning_icon(label): return PLANNING_ICONS.get(label.strip().lower())
def glance_icon(label):
    l = label.lower()
    if "temp" in l: return "temperature"
    if "elev" in l or "ft" in l: return "mountain"
    if "distance" in l: return "road"
    if "driv" in l: return "car"
    if "time" in l or "road" in l: return "clock"
    return None

# ── Flowables ─────────────────────────────────────────────────────────────────
class GoldLine(Flowable):
    def __init__(self, width=None, thickness=0.75):
        Flowable.__init__(self); self._w=width; self._th=thickness
    def wrap(self, aw, ah): self.width=self._w or aw; return self.width, self._th+6
    def draw(self):
        self.canv.setStrokeColor(GOLD); self.canv.setLineWidth(self._th)
        self.canv.line(0, 3, self.width, 3)

class SectionBadge(Flowable):
    """Magazine-style '01  SUMMARY' badge; num='' -> plain gold label, no box."""
    def __init__(self, num, label):
        Flowable.__init__(self); self.num=str(num); self.label=label
    def wrap(self, aw, ah): self.width=aw; return aw, 22
    def draw(self):
        c = self.canv; x = 0
        if self.num:
            c.setFillColor(GREEN); c.roundRect(0, 1, 22, 18, 3, fill=1, stroke=0)
            c.setFillColor(GOLD); c.setFont("Helvetica-Bold", 10)
            c.drawCentredString(11, 6, self.num); x = 30
        c.setFillColor(GOLD); c.setFont("Helvetica-Bold", 7)
        c.drawString(x, 7, spaced(self.label.upper()))

class DayHeader(Flowable):
    def __init__(self, num, title, note=''):
        Flowable.__init__(self); self.num=str(num); self.title=title; self.note=note
    def wrap(self, aw, ah): self.width=aw; return aw, 46
    def draw(self):
        c=self.canv; w,h=self.width,46
        c.setFillColor(GREEN); c.rect(0,0,w,h,fill=1,stroke=0)
        c.setFillColor(GOLD); c.rect(0,0,4,h,fill=1,stroke=0)
        c.setFillColor(GOLD); c.setFont('Helvetica-Bold',7); c.drawString(14,h-15,f'DAY  {self.num}')
        c.setFillColor(white); c.setFont(SERIF, 19); c.drawString(14, h-34, self.title)
        if self.note:
            c.setFillColor(GOLD); c.setFont('Helvetica',7.5)
            nw=c.stringWidth(self.note,'Helvetica',7.5); c.drawString(w-nw-12, h-32, self.note)

class TimelineBlock(Flowable):
    """Vertical timeline: gold spine + node dots, time labels, wrapped copy."""
    def __init__(self, entries):
        Flowable.__init__(self); self.entries=entries
        self.G=20; self.TW=60; self.gap=10; self.pad=13
    def wrap(self, aw, ah):
        self.width=aw; cw=aw-self.G-self.TW-self.gap
        tstyle=ParagraphStyle("tlt",fontName="Helvetica-Bold",fontSize=7.5,leading=10,textColor=GOLD)
        hstyle=ParagraphStyle("tlh",fontName="Helvetica-Bold",fontSize=9.3,leading=12.3,textColor=DARK)
        bstyle=ParagraphStyle("tlb",fontName="Helvetica",fontSize=8.7,leading=12.3,textColor=MED)
        self._laid=[]; total=0
        for e in self.entries:
            tp=Paragraph(e["time"].upper(),tstyle)
            hp=Paragraph(e["title"],hstyle)
            bp=Paragraph(e.get("body",""),bstyle) if e.get("body") else None
            _,th=tp.wrap(self.TW,1000); _,hh=hp.wrap(cw,1000)
            bh=bp.wrap(cw,1000)[1] if bp else 0
            rh=max(th, hh+(bh+3 if bp else 0))+self.pad
            self._laid.append((tp,hp,bp,rh,hh)); total+=rh
        self._cw=cw; self._total=total
        return self.width, total
    def draw(self):
        c=self.canv; xs=self.G/2
        c.setStrokeColor(GOLD); c.setLineWidth(1.0); c.line(xs,6,xs,self._total-6)
        y=self._total
        for tp,hp,bp,rh,hh in self._laid:
            y-=rh; node=y+rh-8
            c.setFillColor(GREEN); c.circle(xs,node,3.4,fill=1,stroke=0)
            c.setStrokeColor(GOLD); c.setLineWidth(1.2); c.circle(xs,node,3.4,fill=0,stroke=1)
            tp.drawOn(c, self.G, node-6)
            hp.drawOn(c, self.G+self.TW+self.gap, y+rh-hh-8)
            if bp: bp.drawOn(c, self.G+self.TW+self.gap, y+8)

class TileRow(Flowable):
    """Stat tiles: optional icon + big value + caption."""
    def __init__(self, tiles, width=None, height=90):
        Flowable.__init__(self); self.tiles=tiles; self._w=width; self._h=height
    def wrap(self, aw, ah): self.width=self._w or aw; return self.width, self._h
    def draw(self):
        c=self.canv; w,h=self.width,self._h; n=len(self.tiles); gap=8
        tw=(w-gap*(n-1))/n
        for i,(value,label,icon) in enumerate(self.tiles):
            x=i*(tw+gap)
            c.setFillColor(SAGE); c.roundRect(x,0,tw,h,4,fill=1,stroke=0)
            c.setFillColor(GOLD); c.rect(x,h-3,tw,3,fill=1,stroke=0)
            if icon: draw_icon(c, icon, GOLD, x+tw/2-7, h-24, 14)
            fs=16 if len(value)<=7 else 12
            c.setFont('Helvetica-Bold',fs); c.setFillColor(GREEN)
            vw=stringWidth(value,'Helvetica-Bold',fs)
            c.drawString(x+(tw-vw)/2, h-46, value)
            c.setFont('Helvetica',6.3); c.setFillColor(MED)
            for j,line in enumerate(label.split('\n')):
                lw=stringWidth(line,'Helvetica',6.3)
                c.drawString(x+(tw-lw)/2, h-58-j*9, line)

class IconPills(Flowable):
    """Activity tags as pills, each led by a small white icon."""
    def __init__(self, items, row_h=26, gap=8, row_gap=9):
        Flowable.__init__(self); self.items=items
        self.row_h=row_h; self.gap=gap; self.row_gap=row_gap
    def _w(self, it): return 11+12+4+stringWidth(it,"Helvetica-Bold",7.3)+12
    def wrap(self, aw, ah):
        self.width=aw; rows,cur,cw=[],[],0
        for it in self.items:
            w=self._w(it); add=w+(self.gap if cur else 0)
            if cur and cw+add>self.width: rows.append(cur); cur,cw=[it],w
            else: cur.append(it); cw+=add
        if cur: rows.append(cur)
        self.rows=rows; self._h=len(rows)*self.row_h+max(0,len(rows)-1)*self.row_gap
        return self.width, self._h
    def draw(self):
        c=self.canv; y=self._h-self.row_h
        for row in self.rows:
            rw=sum(self._w(it) for it in row)+self.gap*(len(row)-1)
            x=(self.width-rw)/2   # centre each row
            for it in row:
                w=self._w(it)
                c.setFillColor(GREEN); c.roundRect(x,y,w,self.row_h,self.row_h/2,fill=1,stroke=0)
                draw_icon(c, activity_icon(it), white, x+11, y+self.row_h/2-6, 12)
                c.setFillColor(white); c.setFont("Helvetica-Bold",7.3)
                c.drawString(x+11+12+4, y+self.row_h/2-2.6, it)
                x+=w+self.gap
            y-=(self.row_h+self.row_gap)

# ── Section builders ──────────────────────────────────────────────────────────
def eat_section(rows):
    hdr=[icon_label_cell("tools-kitchen-2","WHERE TO EAT",white), Paragraph('',ST['eat_hd'])]
    data=[hdr]
    for r in rows:
        rec=[Paragraph(r['place'],ST['eat_val'])]
        if r.get('note'): rec.append(Paragraph(r['note'],ST['eat_note']))
        cat=icon_label_cell(dining_icon(r['category']), r['category'].upper(), TEAL,
                            size=11, letterspaced=False, fs=7.3)
        data.append([cat, rec])
    col1=0.92*inch
    t=Table(data,colWidths=[col1,CW-col1])
    t.setStyle(TableStyle([
        ('BACKGROUND',(0,0),(-1,0),GREEN),('SPAN',(0,0),(-1,0)),
        ('LEFTPADDING',(0,0),(-1,0),8),('TOPPADDING',(0,0),(-1,0),5),('BOTTOMPADDING',(0,0),(-1,0),5),
        ('ROWBACKGROUNDS',(0,1),(-1,-1),[white,SAGE]),('VALIGN',(0,0),(-1,-1),'TOP'),
        ('LEFTPADDING',(0,1),(-1,-1),7),('RIGHTPADDING',(0,1),(-1,-1),7),
        ('TOPPADDING',(0,1),(-1,-1),5),('BOTTOMPADDING',(0,1),(-1,-1),5),
        ('LINEAFTER',(0,1),(0,-1),0.5,RULE),('BOX',(0,0),(-1,-1),0.5,RULE),
    ]))
    return KeepTogether([t])

def cuisine_tally(dining):
    """'Mexican 4 · Thai 1 · Coffee 3' across every entry, most frequent first.

    Derived by the engine, never stored: this is the line that makes an imbalance
    visible, and an imbalance is exactly what a hand-written tally would hide."""
    counts = {}
    for g in dining.get('groups', []):
        for e in g.get('entries', []):
            c = (e.get('cuisine') or '').strip()
            if c:
                key = c[:1].upper() + c[1:]
                counts[key] = counts.get(key, 0) + 1
    if not counts:
        return ''
    ordered = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    return '  ·  '.join('{} {}'.format(k, v) for k, v in ordered)

# Meal slot for a day's `where_to_eat` category, so free-form categories still land in
# the right calendar column. Anything unmapped (a market stall, 'Snack') goes to the
# slot named by its own category if one exists, else to the morning column.
MEAL_SLOTS = ("Morning", "Lunch", "Dinner")
SLOT_OF = {"coffee": "Morning", "breakfast": "Morning", "bakery": "Morning",
           "pastry": "Morning", "brunch": "Lunch", "lunch": "Lunch",
           "dinner": "Dinner", "drinks": "Dinner", "dessert": "Dinner"}
RESERVE_WORDS = ("opentable", "resy", "reserve", "book", "phone", "tock")

def _pick_index(itin):
    """(index, match) from the validator, so a day's pick resolves to a shortlist entry
    by exactly the rule the cross-checks use. Falls back to exact names if the validator
    cannot be imported (jsonschema missing)."""
    try:
        sys.path.insert(0, os.path.join(HERE, 'schema'))
        from validate import _dining_index, _match
        return _dining_index(itin), _match
    except Exception:
        norm = lambda x: " ".join((x or "").split()).casefold()
        idx = {norm(e.get('name')): e for g in (itin.get('dining') or {}).get('groups', [])
               for e in g.get('entries', [])}
        return idx, lambda place, i: (i.get(norm(place)), 'exact') if norm(place) in i else (None, None)

def _day_label(day, i):
    import datetime
    d = day.get('date')
    if d:
        try:
            dt = datetime.date.fromisoformat(d)
            return dt.strftime('%a').upper(), '{} {}'.format(dt.strftime('%b'), dt.day)
        except Exception:
            pass
    if day.get('weekday'):
        return day['weekday'][:3].upper(), 'Day {}'.format(i)
    return 'DAY {}'.format(i), ''

def _needs_booking(e):
    b = (e or {}).get('booking') or ''
    return any(w in b.lower() for w in RESERVE_WORDS)

def pick_cell(place, e, exact=True):
    """One calendar cell entry: name, cuisine and price, one dish, and a booking flag only
    when the place actually takes reservations -- the one action the reader must take."""
    st_name = ps('pcn', fn='Helvetica-Bold', fs=7.6, ld=9.6, col=GREEN)
    st_meta = ps('pcm', fs=6.6, ld=8.6, col=MED)
    # The shortlist name is the clean one, so use it when the day's wording is just that
    # name plus an area ('Lofty Coffee — Solana Beach'). Any other loose match ('Bump
    # Coffee & Prager Brothers') keeps the day's own wording, so the second place in the
    # pick is not silently dropped from the calendar.
    name = place
    if e:
        en = e.get('name') or ''
        rest = place[len(en):].strip() if place.casefold().startswith(en.casefold()) else None
        if exact or (rest is not None and (not rest or rest[0] in '—–-,(')):
            name = en
    out = [Paragraph(name, st_name)]
    if e:
        meta = ' · '.join(x for x in (e.get('cuisine'), e.get('price')) if x)
        if meta:
            out.append(Paragraph(meta, st_meta))
        if e.get('dishes'):
            out.append(Paragraph('<i>{}</i>'.format(e['dishes'][0]), st_meta))
        if _needs_booking(e):
            out.append(Paragraph('<font color="#C4973A"><b>{}</b></font>'.format(e['booking']),
                                 st_meta))
    return out

def dining_calendar(itin):
    """Days down the side, meal slots across: what the itinerary actually picked."""
    idx, match = _pick_index(itin)
    hdr = [Paragraph(spaced(t.upper()), ST['eat_hd']) for t in ('Day',) + MEAL_SLOTS]
    data = [hdr]; picked = set()
    for i, day in enumerate(itin['days'], start=1):
        wd, dt = _day_label(day, i)
        cells = {k: [] for k in MEAL_SLOTS}
        for r in day.get('where_to_eat') or []:
            slot = SLOT_OF.get(r['category'].strip().lower(), 'Morning')
            e, how = match(r['place'], idx)
            if e is not None:
                picked.add(id(e))
            if cells[slot]:
                cells[slot].append(Spacer(1, 4))
            cells[slot] += pick_cell(r['place'], e, exact=(how == 'exact'))
        label = [Paragraph(wd, ps('cdw', fn='Helvetica-Bold', fs=8, ld=10, col=GOLD)),
                 Paragraph(dt, ps('cdd', fs=6.8, ld=9, col=MED))]
        data.append([label] + [cells[k] or Paragraph('—', ps('cde', fs=7, col=PALE))
                               for k in MEAL_SLOTS])
    dw = 0.62 * inch; sw = (CW - dw) / 3
    t = Table(data, colWidths=[dw, sw, sw, sw], repeatRows=1)
    t.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), GREEN), ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [white, SAGE]),
        ('LEFTPADDING', (0, 0), (-1, -1), 6), ('RIGHTPADDING', (0, 0), (-1, -1), 6),
        ('TOPPADDING', (0, 0), (-1, -1), 5), ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
        ('INNERGRID', (0, 1), (-1, -1), 0.4, RULE), ('BOX', (0, 0), (-1, -1), 0.5, RULE),
    ]))
    return t, picked

def maps_url(e, region=''):
    """The entry's own `map_url`, else a Google Maps search for name + area + region --
    a search link, not a pin, so it never points at a guessed address."""
    if e.get('map_url'):
        return e['map_url']
    from urllib.parse import quote_plus
    q = ', '.join(x for x in (e.get('name'), e.get('area'), region) if x)
    return 'https://www.google.com/maps/search/?api=1&query=' + quote_plus(q)

def suggestion_card(e, region=''):
    """A compact shortlist card for the 'Also Suggested' grid. No dishes here -- the
    card's job is to say why and where; a Maps link does the 'where'."""
    st_n = ps('scn', fn='Helvetica-Bold', fs=7.8, ld=9.8, col=GREEN)
    st_m = ps('scm', fs=6.5, ld=8.4, col=MED)
    st_w = ps('scw', fs=6.9, ld=8.8, col=DARK)
    out = [Paragraph(e.get('name', ''), st_n)]
    url = maps_url(e, region).replace('&', '&amp;')
    link = '<link href="{}"><font color="#2A5C52"><b><u>Map</u></b></font></link>'.format(url)
    meta = ' · '.join(x for x in (e.get('area'), e.get('cuisine'), e.get('price')) if x)
    out.append(Paragraph(' · '.join(x for x in (meta, link) if x), st_m))
    bits = []
    if e.get('hours'):
        bits.append(e['hours'])
    if e.get('closed'):
        bits.append('<font color="#C4973A"><b>closed {}</b></font>'.format(
            ', '.join(d[:3] for d in e['closed'])))
    if bits:
        out.append(Paragraph('  ·  '.join(bits), st_m))
    if e.get('why'):
        out.append(Paragraph(e['why'], st_w))
    return out

def suggestion_grid(groups, picked, cols=3, region=''):
    """Unpicked shortlist entries, budget group by budget group, three cards to a row.
    One table, so ReportLab can break it between rows rather than strand a group."""
    cw = CW / cols
    data, cmds, r = [], [], 0
    for g in groups:
        rest = [e for e in g.get('entries') or [] if id(e) not in picked]
        if not rest:
            continue
        data.append([Paragraph(spaced(g['label'].upper()),
                               ps('sgl', fn='Helvetica-Bold', fs=6.8, ld=9, col=GOLD))]
                    + [''] * (cols - 1))
        cmds += [('SPAN', (0, r), (-1, r)), ('LINEBELOW', (0, r), (-1, r), 1.2, GOLD),
                 ('TOPPADDING', (0, r), (-1, r), 8 if r else 0), ('BOTTOMPADDING', (0, r), (-1, r), 3)]
        r += 1
        for k in range(0, len(rest), cols):
            row = [suggestion_card(e, region) for e in rest[k:k + cols]]
            row += [''] * (cols - len(row))
            data.append(row)
            cmds += [('BACKGROUND', (j, r), (j, r), SAGE) for j in range(len(rest[k:k + cols]))]
            cmds += [('LINEBELOW', (0, r), (-1, r), 3, white)]
            r += 1
    if not data:
        return None
    t = Table(data, colWidths=[cw] * cols)
    t.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('LEFTPADDING', (0, 0), (-1, -1), 6), ('RIGHTPADDING', (0, 0), (-1, -1), 6),
        ('TOPPADDING', (0, 0), (-1, -1), 4), ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
        ('LINEAFTER', (0, 0), (-2, -1), 3, white),
    ] + cmds))
    return t

def dining_story(itin, number):
    """'Where to Eat' as two pages: a calendar of what the days picked, then every other
    shortlist entry packed into a compact grid, grouped by budget."""
    dining = itin.get('dining') or {}
    groups = dining.get('groups') or []
    if not groups:
        return []
    s = [SectionBadge(number, 'Dining'), Spacer(1, 7),
         Paragraph(dining.get('heading', 'Where to Eat'), ST['sec_hd']), Spacer(1, 2)]
    if dining.get('note'):
        s += [Paragraph(dining['note'], ps('dn', fs=8.4, ld=12, col=MED)), Spacer(1, 6)]
    cal, picked = dining_calendar(itin)
    s += [icon_label_cell('tools-kitchen-2', 'YOUR PICKS', GOLD, size=11, fs=7),
          GoldLine(width=0.5 * inch, thickness=1.5), Spacer(1, 4), cal]
    tally = cuisine_tally(dining)
    if tally:
        s += [Spacer(1, 8), Paragraph(tally, ps('dt', fn='Helvetica-Bold', fs=7.2, ld=10,
                                                col=TEAL, al=TA_CENTER))]
    s.append(PageBreak())
    grid = suggestion_grid(groups, picked, region=itin['region'].get('title', ''))
    if grid is not None:
        s += [Paragraph(spaced('ALSO SUGGESTED'), ST['sec_lbl']),
              Paragraph('Alternates and backups', ST['sec_hd']), Spacer(1, 2), grid,
              PageBreak()]
    return s

def worth_knowing_section(items):
    hdr=[icon_label_cell("building-monument","WORTH KNOWING",white), Paragraph('',ST['eat_hd'])]
    data=[hdr]
    for it in items:
        data.append([Paragraph(it['place'],ST['eat_cat']), Paragraph(it['blurb'],ST['eat_val'])])
    col1=1.15*inch
    t=Table(data,colWidths=[col1,CW-col1])
    t.setStyle(TableStyle([
        ('BACKGROUND',(0,0),(-1,0),GREEN),('SPAN',(0,0),(-1,0)),
        ('LEFTPADDING',(0,0),(-1,0),8),('TOPPADDING',(0,0),(-1,0),5),('BOTTOMPADDING',(0,0),(-1,0),5),
        ('ROWBACKGROUNDS',(0,1),(-1,-1),[white,CREAM]),('VALIGN',(0,0),(-1,-1),'TOP'),
        ('LEFTPADDING',(0,1),(-1,-1),7),('RIGHTPADDING',(0,1),(-1,-1),7),
        ('TOPPADDING',(0,1),(-1,-1),6),('BOTTOMPADDING',(0,1),(-1,-1),6),
        ('LINEAFTER',(0,1),(0,-1),0.5,RULE),('BOX',(0,0),(-1,-1),0.5,RULE),
    ]))
    return KeepTogether([t])

def info_table(rows, label_w=100, pad=4, compact=False):
    lb,vl=(ps('tbc',fn='Helvetica-Bold',fs=7.6,ld=9.8),ps('tdc',fs=7.6,ld=9.8)) if compact \
          else (ST['tdb'],ST['td'])
    data=[[Paragraph(r['label'],lb), Paragraph(r['value'],vl)] for r in rows]
    t=Table(data,colWidths=[label_w,CW-label_w])
    t.setStyle(TableStyle([
        ('BACKGROUND',(0,0),(0,-1),SAGE),('ROWBACKGROUNDS',(1,0),(1,-1),[white,CREAM]),
        ('VALIGN',(0,0),(-1,-1),'MIDDLE'),
        ('LEFTPADDING',(0,0),(-1,-1),8),('RIGHTPADDING',(0,0),(-1,-1),8),
        ('TOPPADDING',(0,0),(-1,-1),pad),('BOTTOMPADDING',(0,0),(-1,-1),pad),
        ('GRID',(0,0),(-1,-1),0.4,RULE),
    ]))
    return t

def lodging_table(rows):
    head=[Paragraph('NIGHT(S)',ST['th']),Paragraph('DAY(S)',ST['th']),
          Paragraph('AREA & SUGGESTED PROPERTIES',ST['th']),Paragraph('NOTES',ST['th'])]
    data=[head]
    for r in rows:
        area=[Paragraph(r['area'],ST['stay_area'])]
        for p in r.get('properties',[]):
            if p.get('reason'):
                area.append(Paragraph(f"<b>{p['name']}</b> &nbsp;<font color='#555555'>&mdash; {p['reason']}</font>",ST['stay_prop']))
            else:
                area.append(Paragraph(f"<b>{p['name']}</b>",ST['stay_prop']))
        data.append([Paragraph(r['nights'],ST['tdb']),Paragraph(r['days'],ST['td']),area,Paragraph(r['notes'],ST['td'])])
    t=Table(data,colWidths=[0.6*inch,0.55*inch,3.2*inch,CW-4.35*inch])
    t.setStyle(TableStyle([
        ('BACKGROUND',(0,0),(-1,0),GREEN),('ROWBACKGROUNDS',(0,1),(-1,-1),[white,SAGE]),
        ('VALIGN',(0,0),(-1,-1),'TOP'),('VALIGN',(0,0),(-1,0),'MIDDLE'),
        ('LEFTPADDING',(0,0),(-1,-1),5),('RIGHTPADDING',(0,0),(-1,-1),5),
        ('TOPPADDING',(0,0),(-1,-1),3),('BOTTOMPADDING',(0,0),(-1,-1),3),
        ('GRID',(0,0),(-1,-1),0.25,RULE),
    ]))
    return t

# ── Cover contour motif ───────────────────────────────────────────────────────
def make_contour_png(path):
    import matplotlib; matplotlib.use("Agg")
    import matplotlib.pyplot as plt, numpy as np
    np.random.seed(7)
    gx,gy=np.meshgrid(np.linspace(0,6,300),np.linspace(0,4,200))
    field=np.zeros_like(gx)
    for _ in range(6):
        cx,cy,s=np.random.uniform(0,6),np.random.uniform(0,4),np.random.uniform(0.6,1.6)
        field+=np.exp(-(((gx-cx)**2+(gy-cy)**2)/(2*s*s)))
    fig,ax=plt.subplots(figsize=(14,9),dpi=100)
    ax.contour(gx,gy,field,levels=14,colors=MPL_GOLD,linewidths=0.6,alpha=0.5)
    ax.set_axis_off(); ax.margins(0)
    fig.patch.set_alpha(0); ax.patch.set_alpha(0)
    plt.subplots_adjust(left=0,right=1,top=1,bottom=0)
    fig.savefig(path,transparent=True,dpi=100); plt.close(fig)

# ── Route map ─────────────────────────────────────────────────────────────────
def _bbox_for(stops, target_ratio, override=None, pad_frac=0.28):
    if override: return override
    lons=[s['lon'] for s in stops]; lats=[s['lat'] for s in stops]
    lon_c=(min(lons)+max(lons))/2; lat_c=(min(lats)+max(lats))/2
    dlon=max(max(lons)-min(lons),0.5)*(1+2*pad_frac)
    dlat=max(max(lats)-min(lats),0.5)*(1+2*pad_frac)
    cosl=math.cos(math.radians(lat_c))
    if (dlon*cosl)/dlat < target_ratio: dlon=target_ratio*dlat/cosl
    else: dlat=dlon*cosl/target_ratio
    return (lon_c-dlon/2, lat_c-dlat/2, lon_c+dlon/2, lat_c+dlat/2)

def _place_labels(stops, bbox, fw, fh, obstacles=None):
    lon0,lat0,lon1,lat1=bbox
    xppp=(lon1-lon0)/(fw*72.0); yppp=(lat1-lat0)/(fh*72.0)
    gap=7.0; fs=8.0
    def lbox(s,tx,ty,ha,va):
        two=bool(s.get('sublabel'))
        wp=max(len(s['name']),len(s.get('sublabel','')))*fs*0.58+4
        hp=fs*(2.15 if two else 1.25)+3
        w=wp*xppp; h=hp*yppp
        x=tx if ha=='left' else (tx-w if ha=='right' else tx-w/2)
        yt=ty+(h if va=='bottom' else (h/2 if va=='center' else 0))
        return (x,yt-h,x+w,yt)
    def ov(a,b):
        ox=max(0,min(a[2],b[2])-max(a[0],b[0])); oy=max(0,min(a[3],b[3])-max(a[1],b[1]))
        return ox*oy
    mr=6*max(xppp,yppp); markers=[(s['lon'],s['lat']) for s in stops]
    dirs=[(gap,0,'left','center'),(-gap,0,'right','center'),(0,gap,'center','bottom'),
          (0,-gap,'center','top'),(gap,gap,'left','bottom'),(-gap,gap,'right','bottom'),
          (gap,-gap,'left','top'),(-gap,-gap,'right','top')]
    placed=list(obstacles or []); results=[]
    for s in stops:
        if s.get('label_offset'):
            lo=s['label_offset']; r=dict(tx=s['lon']+lo.get('dx',0),ty=s['lat']+lo.get('dy',0),
                                         ha='center',va=lo.get('va','bottom'))
            results.append(r); placed.append(lbox(s,r['tx'],r['ty'],r['ha'],r['va'])); continue
        best=None; bs=None
        for dx,dy,ha,va in dirs:
            tx=s['lon']+dx*xppp; ty=s['lat']+dy*yppp; box=lbox(s,tx,ty,ha,va); sc=0.0
            for ml,mt in markers:
                sc+=ov(box,(ml-mr,mt-mr,ml+mr,mt+mr))*3.0
            for pb in placed: sc+=ov(box,pb)*5.0
            oob=(max(0,lon0-box[0])+max(0,box[2]-lon1))*(lat1-lat0)
            oob+=(max(0,lat0-box[1])+max(0,box[3]-lat1))*(lon1-lon0)
            sc+=oob*8.0
            if bs is None or sc<bs: bs=sc; best=(tx,ty,ha,va,box)
        tx,ty,ha,va,box=best
        results.append(dict(tx=tx,ty=ty,ha=ha,va=va)); placed.append(box)
    return results

def render_route_map(itin, out_path, fig_w=6.6, fig_h=4.0, dpi=300):
    import matplotlib; matplotlib.use('Agg')
    import matplotlib.pyplot as plt, matplotlib.patheffects as pe, numpy as np
    import geopandas as gpd
    from shapely.geometry import box as shp_box
    from PIL import Image as PILImage
    _ensure_map_data()   # download Natural Earth shapefiles on first use
    m=itin['map']; stops=m['stops']; legs=m.get('legs',[])
    bbox=_bbox_for(stops, fig_w/fig_h, override=m.get('bbox'))
    lon0,lat0,lon1,lat1=bbox; clip=shp_box(lon0,lat0,lon1,lat1)
    shp=lambda n: os.path.join(NE_DIR,n,n+'.shp')
    ocean=gpd.read_file(shp('ne_10m_ocean'),bbox=clip)
    states=gpd.read_file(shp('ne_10m_admin_1_states_provinces'),bbox=clip)
    coast=gpd.read_file(shp('ne_10m_coastline'),bbox=clip)
    lakes=gpd.read_file(shp('ne_10m_lakes'),bbox=clip)
    rivers=gpd.read_file(shp('ne_10m_rivers_lake_centerlines'),bbox=clip)
    fig,ax=plt.subplots(figsize=(fig_w,fig_h),dpi=dpi)
    fig.patch.set_facecolor(MPL_CREAM); ax.set_facecolor(MPL_LAND)
    # aspect=None everywhere: geopandas otherwise auto-sets aspect from layer
    # bounds, which is NaN for empty layers (e.g. ocean/coast in landlocked regions).
    if len(ocean): ocean.plot(ax=ax,color=MPL_WATER,zorder=1,aspect=None)
    if len(lakes): lakes.plot(ax=ax,color=MPL_WATER,zorder=2,aspect=None)
    if len(rivers): rivers.plot(ax=ax,color=MPL_WATER,linewidth=0.8,zorder=2,aspect=None)
    # graticule
    for lx in np.arange(math.ceil(lon0),lon1,1):
        ax.axvline(lx,color=MPL_BORDER,lw=0.3,alpha=0.22,zorder=2)
        ax.text(lx,lat0+0.05,f"{abs(int(lx))}°W",fontsize=5,color=MPL_MED,alpha=0.5,ha="center",va="bottom",zorder=2)
    for ly in np.arange(math.ceil(lat0),lat1,1):
        ax.axhline(ly,color=MPL_BORDER,lw=0.3,alpha=0.22,zorder=2)
        ax.text(lon1-0.05,ly,f"{int(ly)}°N",fontsize=5,color=MPL_MED,alpha=0.5,ha="right",va="center",zorder=2)
    if len(states): states.boundary.plot(ax=ax,color=MPL_BORDER,linewidth=0.6,alpha=0.7,linestyle=(0,(4,3)),zorder=3,aspect=None)
    if len(coast): coast.plot(ax=ax,color=MPL_GREEN,linewidth=1.0,zorder=4,aspect=None)
    for a in m.get('annotations',[]):
        ax.text(a['lon'],a['lat'],a['text'],fontsize=a.get('size',7.5),color=MPL_MED,ha='center',
                style='italic',alpha=0.55,zorder=4,path_effects=[pe.withStroke(linewidth=2,foreground=MPL_CREAM)])
    xs=[s['lon'] for s in stops]; ys=[s['lat'] for s in stops]
    ax.plot(xs,ys,color=MPL_GOLD,linewidth=2.0,solid_capstyle='round',zorder=5)
    # leg labels + register them as obstacles so stop labels dodge them
    obstacles=[]
    xppp=(lon1-lon0)/(fig_w*72.0); yppp=(lat1-lat0)/(fig_h*72.0)
    for i,lab in enumerate(legs[:max(0,len(stops)-1)]):
        mx=(xs[i]+xs[i+1])/2; my=(ys[i]+ys[i+1])/2
        ax.text(mx,my,lab,fontsize=5.6,color=MPL_DARK,ha="center",va="center",zorder=8,
                bbox=dict(boxstyle="round,pad=0.25",fc="white",ec=MPL_GOLD,lw=0.5,alpha=0.92))
        wp=len(lab)*5.6*0.6; hp=5.6*1.6
        w=wp*xppp; h=hp*yppp
        obstacles.append((mx-w/2,my-h/2,mx+w/2,my+h/2))
    labels=_place_labels(stops,bbox,fig_w,fig_h,obstacles=obstacles)
    halo=[pe.withStroke(linewidth=2.6,foreground=MPL_CREAM)]
    for s,l in zip(stops,labels):
        ax.scatter([s['lon']],[s['lat']],s=60,facecolor=MPL_GREEN,edgecolor=MPL_GOLD,linewidth=1.3,zorder=6)
        ax.text(l['tx'],l['ty'],s['name'],fontsize=8,fontweight='bold',color=MPL_GREEN,
                ha=l['ha'],va=l['va'],zorder=7,path_effects=halo)
        if s.get('sublabel'):
            dy=-(lat1-lat0)*0.028
            ax.text(l['tx'],l['ty']+(dy if l['va']!='top' else -abs(dy)),s['sublabel'],
                    fontsize=6.2,color=MPL_MED,ha=l['ha'],va='top',zorder=7,
                    path_effects=[pe.withStroke(linewidth=2.2,foreground=MPL_CREAM)])
    cx=lon0+(lon1-lon0)*0.93; cy=lat0+(lat1-lat0)*0.87; rr=(lat1-lat0)*0.05
    ax.annotate('',xy=(cx,cy+rr),xytext=(cx,cy-rr*0.4),arrowprops=dict(arrowstyle='-|>',color=MPL_DARK,lw=1.1))
    ax.text(cx,cy+rr*1.6,'N',fontsize=8,color=MPL_DARK,ha='center',fontweight='bold')
    ax.set_xlim(lon0,lon1); ax.set_ylim(lat0,lat1)
    ax.set_aspect(1/math.cos(math.radians((lat0+lat1)/2)))
    ax.set_xticks([]); ax.set_yticks([])
    for sp in ax.spines.values(): sp.set_visible(False)
    plt.subplots_adjust(left=.005,right=.995,top=.995,bottom=.005)
    plt.savefig(out_path,dpi=dpi,facecolor=fig.get_facecolor(),pil_kwargs={'quality':87})
    plt.close(fig)
    with PILImage.open(out_path) as im: return im.size

# ── Page decorators ───────────────────────────────────────────────────────────
def spaced_gap(text): return '  '.join(list(text.replace('  ',' ')))

def make_cover_page(itin, contour_png):
    meta=itin['meta']; region=itin['region']; cover=itin.get('cover',{})
    kicker=cover.get('kicker',meta['doc_kind'])
    duration=cover.get('duration_label',f"{meta['nights']} Nights · {meta['days']} Days")
    stats=cover.get('stats',[]); waypoints=region.get('waypoints',[])
    def cover_page(canvas, doc):
        canvas.saveState()
        band_h=round(H*0.5); band_bot=H-band_h
        canvas.setFillColor(GREEN); canvas.rect(0,band_bot,W,band_h,fill=1,stroke=0)
        if os.path.exists(contour_png):
            canvas.drawImage(contour_png,0,band_bot,W,band_h,mask='auto')
        canvas.setFont('Helvetica',8); canvas.setFillColor(white)
        canvas.drawCentredString(W/2,H-72,spaced(kicker.upper()))
        canvas.setStrokeColor(GOLD); canvas.setLineWidth(0.75); canvas.line(1.7*inch,H-92,W-1.7*inch,H-92)
        canvas.setFont(SERIF,46); canvas.setFillColor(white)
        canvas.drawCentredString(W/2,H-168,region['title'])
        canvas.setFont(SERIF,17); canvas.setFillColor(GOLD)
        canvas.drawCentredString(W/2,H-196,region['subtitle'])
        if waypoints:
            canvas.setFont('Helvetica',7.5); canvas.setFillColor(SAGE)
            canvas.drawCentredString(W/2,band_bot+16,'  |  '.join(waypoints))
        # date block, centred in the lower white area (no seal, no footer strip)
        canvas.setStrokeColor(GOLD); canvas.setLineWidth(0.6)
        canvas.line(2.3*inch,280,W-2.3*inch,280)
        canvas.setFont(SERIF,24); canvas.setFillColor(GREEN)
        canvas.drawCentredString(W/2,250,meta['date_label'].upper())
        canvas.setFont('Helvetica',10); canvas.setFillColor(MED)
        canvas.drawCentredString(W/2,232,spaced_gap(duration.upper()))
        canvas.setStrokeColor(GOLD); canvas.setLineWidth(0.6)
        canvas.line(2.3*inch,216,W-2.3*inch,216)
        if stats:
            bw=1.28*inch; bg=0.17*inch
            tot=len(stats)*bw+(len(stats)-1)*bg; sx=(W-tot)/2; bh=66; sy=120
            for i,st in enumerate(stats):
                bx=sx+i*(bw+bg)
                canvas.setFillColor(SAGE); canvas.roundRect(bx,sy,bw,bh,4,fill=1,stroke=0)
                canvas.setFillColor(GOLD); canvas.rect(bx,sy+bh-4,bw,4,fill=1,stroke=0)
                num=str(st['value']); fs=24 if len(num)<=2 else 17
                canvas.setFont('Helvetica-Bold',fs); canvas.setFillColor(GREEN)
                canvas.drawCentredString(bx+bw/2,sy+bh-34+(0 if fs==24 else 4),num)
                canvas.setFont('Helvetica',6.5); canvas.setFillColor(MED)
                for j,line in enumerate(st['label'].upper().split('\n')):
                    canvas.drawCentredString(bx+bw/2,sy+20-j*10,line)
        canvas.restoreState()
    return cover_page

def make_body_page(itin):
    meta=itin['meta']; region=itin['region']
    running=f"{region['title']}     |     {meta['doc_kind']}     |     {meta['date_label']}".upper()
    note=meta.get('footer_note','For personal use only')
    def body_page(canvas, doc):
        canvas.saveState()
        canvas.setFillColor(GREEN); canvas.rect(0,H-HEADER_H,W,HEADER_H,fill=1,stroke=0)
        canvas.setFont('Helvetica',6.5); canvas.setFillColor(SAGE); canvas.drawString(LM,H-18,running)
        canvas.setFont('Helvetica-Bold',7); canvas.setFillColor(GOLD); canvas.drawRightString(W-RM,H-18,str(doc.page-1))
        canvas.setStrokeColor(GOLD); canvas.setLineWidth(0.5); canvas.line(LM,34,W-RM,34)
        canvas.setFont('Helvetica',6.5); canvas.setFillColor(PALE); canvas.drawString(LM,20,note)
        canvas.restoreState()
    return body_page

# ── Story ─────────────────────────────────────────────────────────────────────
def build_story(itin, map_path):
    s=[NextPageTemplate('body'), PageBreak()]
    summ=itin['summary']
    # Section numbers run in sequence over the sections actually present. Hardcoding them
    # leaves a gap ('01' then '03') on any trip that omits an optional page.
    _n=[0]
    def num():
        _n[0]+=1
        return '{:02d}'.format(_n[0])
    # SUMMARY
    s+=[SectionBadge(num(),'Summary'), Spacer(1,7),
        Paragraph(summ.get('route_heading','Your Route'), ST['sec_hd']), Spacer(1,5),
        Paragraph(summ['intro'], ps('intro', fs=9.3, ld=15.5, al=TA_JUSTIFY)), Spacer(1,16)]
    map_w,map_h=render_route_map(itin, map_path)
    img_h=214.0; img_w=img_h*(map_w/map_h)
    if img_w>CW-12: img_w=CW-12; img_h=img_w*(map_h/map_w)
    rl=RLImage(map_path,width=img_w,height=img_h); mt=Table([[rl]],colWidths=[img_w]); mt.hAlign='CENTER'
    mt.setStyle(TableStyle([('BOX',(0,0),(-1,-1),0.75,RULE),
        ('LEFTPADDING',(0,0),(-1,-1),6),('RIGHTPADDING',(0,0),(-1,-1),6),
        ('TOPPADDING',(0,0),(-1,-1),6),('BOTTOMPADDING',(0,0),(-1,-1),6),
        ('BACKGROUND',(0,0),(-1,-1),white)]))
    s+=[KeepTogether([mt]), Spacer(1,16)]
    if summ.get('glance_tiles'):
        glance_lbl=ps('gl', fn='Helvetica-Bold', fs=7.5, col=GOLD, al=TA_CENTER)
        s+=[Paragraph(f'<u>{spaced("TRIP AT A GLANCE")}</u>', glance_lbl), Spacer(1,10)]
        tiles=[(t['value'],t['label'].upper(),glance_icon(t['label'])) for t in summ['glance_tiles']]
        s+=[TileRow(tiles,height=84), Spacer(1,16)]
    if summ.get('activity_tags'):
        s+=[IconPills(summ['activity_tags']), Spacer(1,14)]
    if summ.get('highlights'):
        hl=summ['highlights']; n=len(hl)
        st=ps('hlc',fs=7.4,ld=13,al=TA_CENTER,col=DARK)
        row=[Paragraph(f'<b><font color="#1E3D2F">{h["name"]}</font></b><br/><br/>'
                       f'<font color="#555555">{h["desc"]}</font>',st) for h in hl]
        tbl=Table([row],colWidths=[CW/n]*n)
        cmds=[('BACKGROUND',(0,0),(-1,-1),SAGE),('VALIGN',(0,0),(-1,-1),'MIDDLE'),
              ('LEFTPADDING',(0,0),(-1,-1),6),('RIGHTPADDING',(0,0),(-1,-1),6),
              ('TOPPADDING',(0,0),(-1,-1),16),('BOTTOMPADDING',(0,0),(-1,-1),16)]
        for col in range(n-1): cmds.append(('LINEAFTER',(col,0),(col,0),0.5,RULE))
        for col in range(n): cmds.append(('LINEABOVE',(col,0),(col,0),1.5,GOLD))
        tbl.setStyle(TableStyle(cmds)); s+=[KeepTogether([tbl]), Spacer(1,16)]
    s.append(PageBreak())

    # PLANNING
    planning=itin.get('planning')
    if planning and planning.get('sections'):
        s+=[SectionBadge(num(),'Planning'), Spacer(1,6)]
        for sec in planning['sections']:
            ic=planning_icon(sec['label'])
            label=icon_label_cell(ic, sec['label'].upper(), GOLD, size=11, fs=7) if ic \
                  else Paragraph(spaced(sec['label'].upper()), ST['sec_lbl'])
            block=[label, GoldLine(width=0.5*inch,thickness=1.5), Spacer(1,3)]
            if sec['type']=='info': block.append(info_table(sec['rows'],label_w=100))
            elif sec['type']=='lodging': block.append(lodging_table(sec['rows']))
            s.append(KeepTogether(block)); s.append(Spacer(1,6))
        s.append(PageBreak())

    # PARKING — its own page, so a stop-by-stop guide never spills Planning onto a third page
    parking=itin.get('parking')
    if parking and parking.get('sections'):
        s+=[SectionBadge(num(),'Parking'), Spacer(1,7),
            Paragraph(parking.get('heading','Where to Park'), ST['sec_hd']), Spacer(1,2)]
        if parking.get('note'):
            s+=[Paragraph(parking['note'], ps('pkn', fs=8.4, ld=12, col=MED)), Spacer(1,4)]
        for sec in parking['sections']:
            block=[Paragraph(spaced(sec['label'].upper()), ST['sec_lbl']),
                   info_table(sec['rows'],label_w=118,pad=2.5,compact=True)]
            s.append(KeepTogether(block))
        s.append(PageBreak())

    # DINING — the shortlist every day pick was drawn from, between planning and the days
    s+=dining_story(itin, num() if (itin.get('dining') or {}).get('groups') else '')

    # DAY PAGES
    for i,day in enumerate(itin['days'],start=1):
        s+=[DayHeader(day.get('label',i), day['title'], day.get('subtitle','')), Spacer(1,10),
            TimelineBlock(day['timeline'])]
        if day.get('where_to_eat'): s+=[Spacer(1,7), eat_section(day['where_to_eat'])]
        if day.get('worth_knowing'): s+=[Spacer(1,9), worth_knowing_section(day['worth_knowing'])]
        s.append(PageBreak())

    # PACKING
    packing=itin.get('packing')
    if packing and packing.get('items'):
        s+=[SectionBadge('','Packing Essentials'), Spacer(1,7),
            Paragraph(packing.get('heading','What to Bring'), ST['sec_hd']), Spacer(1,4)]
        rows=[[Paragraph(it['label'],ST['tdb']),Paragraph(it['body'],ST['td'])] for it in packing['items']]
        pt=Table(rows,colWidths=[1.6*inch,CW-1.6*inch])
        pt.setStyle(TableStyle([('ROWBACKGROUNDS',(0,0),(-1,-1),[white,SAGE]),('VALIGN',(0,0),(-1,-1),'TOP'),
            ('LEFTPADDING',(0,0),(-1,-1),7),('RIGHTPADDING',(0,0),(-1,-1),7),
            ('TOPPADDING',(0,0),(-1,-1),7),('BOTTOMPADDING',(0,0),(-1,-1),7),
            ('GRID',(0,0),(-1,-1),0.25,RULE)]))
        s.append(KeepTogether([pt]))
        if packing.get('footnote'):
            s+=[Spacer(1,12),GoldLine(),Spacer(1,10),Paragraph(packing['footnote'],ST['fn'])]
    return s

# ── Build ─────────────────────────────────────────────────────────────────────
def build(itin, out_path, map_path, contour_png):
    make_contour_png(contour_png)
    doc=BaseDocTemplate(out_path,pagesize=letter,leftMargin=LM,rightMargin=RM,
        topMargin=HEADER_H+8,bottomMargin=FOOTER_H,
        title=itin['meta'].get('title',f"{itin['region']['title']} — {itin['meta']['doc_kind']}"),
        author=itin['meta'].get('author','Travel Concierge'))
    cf=Frame(0,0,W,H,leftPadding=0,rightPadding=0,topPadding=0,bottomPadding=0,id='cf')
    bf=Frame(LM,FOOTER_H,CW,FRAME_H,leftPadding=0,rightPadding=0,topPadding=6,bottomPadding=0,id='bf')
    doc.addPageTemplates([
        PageTemplate(id='cover',frames=[cf],onPage=make_cover_page(itin,contour_png)),
        PageTemplate(id='body', frames=[bf],onPage=make_body_page(itin)),
    ])
    doc.build(build_story(itin, map_path))

def validate_instance(itin):
    try: from jsonschema import Draft202012Validator
    except Exception: return
    sp=os.path.join(HERE,'schema','itinerary.schema.json')
    if not os.path.exists(sp): return
    schema=json.load(open(sp,encoding='utf-8'))
    errs=sorted(Draft202012Validator(schema).iter_errors(itin),key=lambda e:list(e.path))
    if errs:
        msgs="\n".join(f"  - at {'/'.join(str(p) for p in e.path) or '(root)'}: {e.message}" for e in errs[:20])
        raise SystemExit(f"Schema validation failed ({len(errs)} error(s)):\n{msgs}")
    # The cross-checks the schema cannot express — chiefly a day scheduling a restaurant
    # on a weekday it is closed. Build-time, because a PDF that ships that is worse than
    # one that fails to build.
    try:
        sys.path.insert(0, os.path.join(HERE, 'schema'))
        from validate import cross_checks
    except Exception:
        return
    xerrs, warns = cross_checks(itin)
    for w in warns:
        print(f"  warning: {w}", file=sys.stderr)
    if xerrs:
        msgs="\n".join(f"  - {e}" for e in xerrs)
        raise SystemExit(f"Itinerary cross-checks failed ({len(xerrs)} error(s)):\n{msgs}")

def main():
    ap=argparse.ArgumentParser(description="Build an itinerary PDF from a JSON instance.")
    ap.add_argument("json_path"); ap.add_argument("--out")
    args=ap.parse_args()
    itin=json.load(open(args.json_path,encoding='utf-8'))
    validate_instance(itin)
    out_dir=os.path.join(os.getcwd(),'output'); os.makedirs(out_dir,exist_ok=True)
    out=args.out or os.path.join(out_dir,itin['meta'].get('output_filename','Itinerary.pdf'))
    build(itin, out, os.path.join(out_dir,'_route_map.jpg'), os.path.join(out_dir,'_contour.png'))
    print(f"Done: {out}  ({os.path.getsize(out)/1e6:.2f} MB, {len(itin['days'])} day pages)")

if __name__ == '__main__':
    main()
