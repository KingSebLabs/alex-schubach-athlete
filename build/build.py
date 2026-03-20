"""
build.py
--------
Builds index.html, sitemap.xml, and robots.txt from:
  - build/template.html        (Jinja2 HTML template)
  - content.yaml               (editable site content)
  - Dropbox XLSX (live)        (race results + calendar)
  - images/gallery/            (photo files)

Usage:
  python3 build/build.py
"""

import sys
import io
import re
import datetime
import requests
from pathlib import Path

import yaml
from jinja2 import Environment, FileSystemLoader, Undefined
from PIL import Image

# ─── Paths ───────────────────────────────────────────────────────────────────
ROOT = Path(__file__).parent.parent
BUILD_DIR = ROOT / "build"
IMAGES_DIR = ROOT / "images"
GALLERY_DIR = IMAGES_DIR / "gallery"

# ─── Dropbox Excel config ─────────────────────────────────────────────────────
DROPBOX_XLSX_URL = (
    "https://www.dropbox.com/scl/fi/eaob1d71j6254uz0oocn8/Racing-Calendar.xlsx"
    "?rlkey=zczjnw5wnongwf6091jj82lpp&st=50slpji0&dl=1"
)
SHEET_NAMES = ["2025", "2026", "2027"]

# The year tab active by default on the race results section
CURRENT_YEAR = "2026"

# Alex's UTMB runner profile URL — used to auto-fetch the live UTMB Index at build time
UTMB_RUNNER_URL = "https://utmb.world/en/runner/8058767.alex.schubach"


def _fmt_cell(v) -> str:
    """Convert a cell value to a clean string; formats dates as '1 Jan 2025', times as H:MM:SS."""
    if v is None:
        return ""
    if isinstance(v, datetime.time):
        return v.strftime("%-H:%M:%S").strip()
    if isinstance(v, datetime.timedelta):
        total = int(v.total_seconds())
        h, rem = divmod(total, 3600)
        m, s = divmod(rem, 60)
        return f"{h}:{m:02d}:{s:02d}"
    if hasattr(v, "strftime"):  # datetime.datetime or datetime.date
        return v.strftime("%-d %b %Y").strip()
    return str(v).strip()


def fetch_excel_sheets(url: str) -> dict:
    """Download XLSX from Dropbox and return {sheet_name: [row_dicts]}."""
    import openpyxl
    try:
        resp = requests.get(url, timeout=30)
        resp.raise_for_status()
        wb = openpyxl.load_workbook(io.BytesIO(resp.content), data_only=True)
        result = {}
        for name in SHEET_NAMES:
            if name not in wb.sheetnames:
                continue
            ws = wb[name]
            rows = list(ws.iter_rows(values_only=True))
            if not rows:
                result[name] = []
                continue
            # Find header row (first non-empty row)
            header_idx = next((i for i, r in enumerate(rows) if any(c for c in r)), None)
            if header_idx is None:
                result[name] = []
                continue
            headers = [str(c).strip() if c else "" for c in rows[header_idx]]
            result[name] = [
                {headers[i]: (_fmt_cell(v)) for i, v in enumerate(row) if i < len(headers)}
                for row in rows[header_idx + 1:]
                if any(v for v in row)
            ]
        return result
    except Exception as e:
        print(f"  ⚠ Could not fetch Excel from Dropbox: {e}", file=sys.stderr)
        return {}


def fetch_utmb_index(runner_url: str, fallback: str = "") -> str:
    """Fetch live UTMB Index from runner's utmb.world profile via __NEXT_DATA__ JSON."""
    import json
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                          "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }
        resp = requests.get(runner_url, timeout=15, headers=headers)
        resp.raise_for_status()
        m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', resp.text, re.DOTALL)
        if not m:
            print("  ⚠ UTMB: __NEXT_DATA__ not found in page", file=sys.stderr)
            return fallback
        data = json.loads(m.group(1))
        perf = data["props"]["pageProps"]["performanceIndexes"]
        numeric = [int(entry["index"]) for entry in perf if isinstance(entry.get("index"), int)]
        if numeric:
            best = str(max(numeric))
            print(f"  UTMB Index fetched: {best} (raw: {perf})")
            return best
    except Exception as e:
        print(f"  ⚠ Could not fetch UTMB index: {e}", file=sys.stderr)
    return fallback


def optimize_images():
    """Resize gallery images to max 1200px wide, quality 82. Modifies in-place."""
    for img_path in GALLERY_DIR.glob("*.jpg"):
        try:
            img = Image.open(img_path)
            if img.width > 1200:
                ratio = 1200 / img.width
                new_size = (1200, int(img.height * ratio))
                img = img.resize(new_size, Image.LANCZOS)
                img.save(img_path, "JPEG", quality=82, optimize=True)
                print(f"  Resized {img_path.name} → {new_size[0]}×{new_size[1]}")
        except Exception as e:
            print(f"  ⚠ Could not optimise {img_path.name}: {e}", file=sys.stderr)

    # Also optimise about.jpg
    about_path = IMAGES_DIR / "about.jpg"
    if about_path.exists():
        try:
            img = Image.open(about_path)
            if img.width > 1200:
                ratio = 1200 / img.width
                img = img.resize((1200, int(img.height * ratio)), Image.LANCZOS)
                img.save(about_path, "JPEG", quality=82, optimize=True)
        except Exception as e:
            print(f"  ⚠ Could not optimise about.jpg: {e}", file=sys.stderr)


def build_gallery_html() -> str:
    """Scan images/gallery/ and build gallery item HTML."""
    images = sorted(GALLERY_DIR.glob("*.jpg")) + sorted(GALLERY_DIR.glob("*.jpeg")) + sorted(GALLERY_DIR.glob("*.png"))
    if not images:
        return "<!-- No gallery images found -->"
    items = []
    for i, img in enumerate(images):
        # Use filename (without extension) as alt text, replacing _ with space
        alt = img.stem.lstrip("0123456789").strip("_- ").replace("_", " ").title()
        items.append(
            f'      <div class="gallery-item reveal" data-index="{i}" data-src="images/gallery/{img.name}">'
            f'<img src="images/gallery/{img.name}" alt="{alt}" loading="lazy"></div>'
        )
    return "\n".join(items)


# ─── Excel/Sheets column name helpers ────────────────────────────────────────

def find_col(row: dict, *candidates) -> str:
    """Find first matching column key (case-insensitive, strips whitespace)."""
    keys_lower = {k.strip().lower(): k for k in row.keys() if k is not None}
    for candidate in candidates:
        if candidate.lower() in keys_lower:
            val = row[keys_lower[candidate.lower()]]
            return (val or "").strip()
    return ""


def parse_race_rows(rows: list[dict]) -> tuple[list[dict], list[dict]]:
    """
    Split sheet rows into (past_races, upcoming_races).
    A row is a past race if RACE RESULTS is non-empty.
    A row is upcoming if RACE RESULTS is empty but EVENT is non-empty.
    Filters to rows where REGISTERED contains 'Alex' OR is empty (TBC upcoming).
    """
    past, upcoming = [], []
    for row in rows:
        event = find_col(row, "EVENT", "Event", "RACE", "Race")
        if not event or event.lower().startswith("event"):  # skip header rows
            continue
        registered = find_col(row, "REGISTERED", "Registered", "REGISTRATION")
        reg_lower = registered.lower()
        # Include if not registered column (older sheets), or "yes"/"tbc" in value
        if registered and "yes" not in reg_lower and "tbc" not in reg_lower:
            continue

        result = find_col(row, "RACE RESULTS", "Race Results", "RESULT", "Results", "TIME")
        date_str = find_col(row, "RACE DATE", "BLACKOUT DATES", "DATE", "Date")
        race_type = find_col(row, "RACE TYPE", "TYPE") or infer_race_type(event.split("\n")[0].strip())
        col_distance = find_col(row, "RACE DISTANCE", "DISTANCE")
        description = find_col(row, "RACE DESCRIPTION", "DESCRIPTION")[:140]
        location = find_col(row, "RACE LOCATION", "LOCATION", "VENUE", "CITY")
        comments_pre = find_col(row, "COMMENTS PRE", "Comments Pre", "PRE RACE", "GOING IN")
        comments_post = find_col(row, "COMMENTS POST", "Comments Post", "POST RACE", "LOOKING BACK")
        pos_overall = find_col(row, "POSITION OVERALL", "Position Overall", "OVERALL POSITION", "POS OVERALL")
        pos_ag = find_col(row, "POSITION AG", "Position AG", "AG POSITION", "AGE GROUP POS")

        race_name = event.split("\n")[0].strip()
        race_date = date_str.split("\n")[0].strip() if date_str else ""
        distance = col_distance or infer_distance(race_name)

        entry = {
            "name": race_name,
            "date": race_date,
            "type": race_type,
            "result": result,
            "description": description,
            "registered": registered,
            "location": location,
            "comments_pre": comments_pre,
            "comments_post": comments_post,
            "pos_overall": pos_overall,
            "pos_ag": pos_ag,
            "distance": distance,
        }

        if result:
            past.append(entry)
        elif race_name:
            upcoming.append(entry)

    return past, upcoming


def infer_race_type(name: str) -> str:
    """Guess race type from name (fallback when RACE TYPE column is absent)."""
    n = name.lower()
    if "hyrox" in n:
        return "Hybrid"
    if "spartan" in n:
        return "OCR"
    if "marathon" in n and "half" not in n:
        return "Road"
    if "half marathon" in n or "half" in n:
        return "Road"
    if "10k" in n or "10km" in n:
        return "Road"
    if "5k" in n or "5km" in n:
        return "Road"
    if "ultra" in n or "80k" in n or "100k" in n:
        return "Ultra"
    if "trail" in n or "mountain" in n or "fuji" in n or "nikko" in n:
        return "Trail"
    return "Road"


def infer_distance(name: str) -> str:
    """Extract distance label from race name."""
    n = name.lower()
    if "marathon" in n and "half" not in n:
        return "42.2 km"
    if "half marathon" in n or "half" in n:
        return "21.1 km"
    if "80k" in n or "80km" in n:
        return "80 km"
    if "50k" in n or "50km" in n:
        return "50 km"
    if "35k" in n or "35km" in n:
        return "35 km"
    if "30k" in n or "30km" in n:
        return "30 km"
    if "27k" in n or "27km" in n:
        return "27 km"
    if "25k" in n or "25km" in n:
        return "25 km"
    if "21k" in n or "21km" in n:
        return "21.1 km"
    if "20k" in n or "20km" in n:
        return "20 km"
    if "12k" in n or "12km" in n:
        return "12 km"
    if "10k" in n or "10km" in n:
        return "10 km"
    if "5k" in n or "5km" in n:
        return "5 km"
    return "—"


def build_race_card_html(race: dict) -> str:
    """Build a single collapsible race card."""
    name = race["name"]
    date = race["date"]
    result = race["result"]
    race_type = race["type"]
    distance = race.get("distance", "—")
    pos = race["pos_overall"] or "—"
    pos_ag = race.get("pos_ag") or "—"

    # Narrative body
    body_parts = []
    if race["comments_pre"]:
        body_parts.append(
            f'              <div class="race-narrative">\n'
            f'                <div class="race-narrative-label">Going In</div>\n'
            f'                <p>{race["comments_pre"]}</p>\n'
            f'              </div>'
        )
    if race["comments_post"]:
        body_parts.append(
            f'              <div class="race-narrative">\n'
            f'                <div class="race-narrative-label">Looking Back</div>\n'
            f'                <p>{race["comments_post"]}</p>\n'
            f'              </div>'
        )

    body_html = "\n".join(body_parts) if body_parts else "              <p>Race notes coming soon.</p>"

    return f'''        <div class="race-item">
          <div class="race-header">
            <div><div class="race-h-name">{name}</div><div class="race-h-sub">{date}</div></div>
            <div class="race-h-dist">{distance}</div>
            <div class="race-h-type">{race_type}</div>
            <div class="race-h-time">{result or "—"}</div>
            <div class="race-h-pos">{pos}</div>
            <div class="race-h-expand">Expand</div>
          </div>
          <div class="race-body">
            <div class="race-body-inner">
{body_html}
            </div>
          </div>
        </div>'''


def build_calendar_card_html(race: dict) -> str:
    """Build a calendar card for an upcoming race."""
    tbc = "tbc" in race.get("registered", "").lower()
    tbc_badge = '<span class="cal-tbc">TBC</span>' if tbc else ""
    # Build sub-details line: type · distance · location (only non-empty parts)
    detail_parts = [p for p in [race.get("type"), race.get("distance"), race.get("location")] if p and p != "—"]
    details = " · ".join(detail_parts)
    desc_html = f'        <div class="cal-desc">{race["description"]}</div>\n' if race.get("description") else ""
    return (
        f'      <div class="cal-card reveal">\n'
        f'        <div class="cal-month">{race["date"]} {tbc_badge}</div>\n'
        f'        <div class="cal-race">{race["name"].upper()}</div>\n'
        f'        <div class="cal-details">{details}</div>\n'
        f'{desc_html}'
        f'      </div>'
    )


TABLE_HEADER = '''      <div class="race-table-header">
        <div class="race-th">Race</div>
        <div class="race-th">Class / Distance</div>
        <div class="race-th">Type</div>
        <div class="race-th">Time</div>
        <div class="race-th">Ranking</div>
        <div class="race-th race-th-expand">Expand</div>
      </div>'''


def build_race_tabs_and_panels(sheets_data: dict) -> tuple:
    """
    Build the year-tabs + year-panels HTML from all sheets.
    sheets_data = { "2025": (past_races, upcoming), "2026": (past_races, upcoming), ... }
    Returns (tabs_and_panels_html, calendar_cards_html, calendar_year)
    """
    # Sort years ascending so tabs appear 2025 → 2026 → ...
    years = sorted(sheets_data.keys())

    tabs_html = '<div class="year-tabs reveal">\n'
    panels_html = ""
    all_upcoming = []

    for sheet_name in years:
        year_full = sheet_name  # already "2025", "2026", etc.
        past_races, upcoming_races = sheets_data[sheet_name]
        is_current = year_full == CURRENT_YEAR

        tabs_html += f'  <div class="year-tab{" active" if is_current else ""}" data-year="{year_full}">{year_full}</div>\n'

        race_cards = "\n".join(build_race_card_html(r) for r in past_races) if past_races else \
            '        <p style="color:var(--grey-mid);padding:2rem 0">No results recorded yet.</p>'

        panels_html += (
            f'\n    <div class="year-panel{" active" if is_current else ""}" id="panel-{year_full}">\n'
            f'{TABLE_HEADER}\n'
            f'      <div class="race-accordion">\n'
            f'{race_cards}\n'
            f'      </div>\n'
            f'    </div>'
        )

        all_upcoming.extend(upcoming_races)

    tabs_html += "</div>"

    calendar_html = "\n".join(build_calendar_card_html(r) for r in all_upcoming) if all_upcoming else \
        '      <p style="color:var(--grey-mid)">Calendar coming soon.</p>'

    return tabs_html + panels_html, calendar_html, CURRENT_YEAR


def build_seo_tags(site: dict, social: dict) -> str:
    """Build Open Graph, Twitter Card, and JSON-LD tags."""
    base_url = site.get("base_url", "")
    title = site.get("title", "Alex Schubach — Endurance Athlete")
    description = site.get("description", "")
    instagram = social.get("instagram", "#")
    strava = social.get("strava", "#")

    og = f'''  <!-- Open Graph -->
  <meta property="og:title" content="{title}">
  <meta property="og:description" content="{description}">
  <meta property="og:image" content="{base_url}/images/about.jpg">
  <meta property="og:url" content="{base_url}">
  <meta property="og:type" content="website">
  <meta name="twitter:card" content="summary_large_image">
  <meta name="twitter:title" content="{title}">
  <meta name="twitter:description" content="{description}">
  <meta name="twitter:image" content="{base_url}/images/about.jpg">'''

    same_as = [s for s in [instagram, strava] if s and s != "#"]
    same_as_json = ", ".join(f'"{s}"' for s in same_as)

    jsonld = f'''  <!-- JSON-LD Structured Data -->
  <script type="application/ld+json">
  {{
    "@context": "https://schema.org",
    "@type": "Person",
    "name": "Alex Schubach",
    "url": "{base_url}",
    "image": "{base_url}/images/about.jpg",
    "jobTitle": "Endurance Athlete",
    "description": "{description}",
    "sameAs": [{same_as_json}]
  }}
  </script>'''

    return og + "\n" + jsonld


def build_analytics_tags(analytics: dict) -> str:
    """Build GA4 or Plausible analytics script tag."""
    ga4_id = analytics.get("ga4_id", "").strip()
    plausible_domain = analytics.get("plausible_domain", "").strip()

    if ga4_id:
        return f'''  <!-- Google Analytics 4 -->
  <script async src="https://www.googletagmanager.com/gtag/js?id={ga4_id}"></script>
  <script>
    window.dataLayer = window.dataLayer || [];
    function gtag(){{dataLayer.push(arguments);}}
    gtag('js', new Date());
    gtag('config', '{ga4_id}');
  </script>'''
    elif plausible_domain:
        return f'  <script defer data-domain="{plausible_domain}" src="https://plausible.io/js/script.js"></script>'

    return "  <!-- Analytics: set ga4_id or plausible_domain in content.yaml -->"


def build_sitemap(base_url: str) -> str:
    today = datetime.date.today().isoformat()
    # Ensure trailing slash removed for consistency
    url = base_url.rstrip("/")
    return f'''<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url>
    <loc>{url}/</loc>
    <lastmod>{today}</lastmod>
    <changefreq>weekly</changefreq>
    <priority>1.0</priority>
  </url>
</urlset>
'''


def build_robots(base_url: str) -> str:
    url = base_url.rstrip("/")
    return f'''User-agent: *
Allow: /
Sitemap: {url}/sitemap.xml
'''


# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    print("\n=== Alex Schubach site builder ===\n")

    # 1. Load content.yaml
    content_path = ROOT / "content.yaml"
    if not content_path.exists():
        print("Error: content.yaml not found", file=sys.stderr)
        sys.exit(1)
    with open(content_path) as f:
        content = yaml.safe_load(f)

    site = content.get("site", {})
    base_url = site.get("base_url", "").rstrip("/")

    # 1b. Fetch live UTMB index (overrides content.yaml fallback)
    indices = content.get("indices", {})
    print("Fetching UTMB index...")
    live_utmb = fetch_utmb_index(UTMB_RUNNER_URL, fallback=indices.get("utmb", ""))
    if live_utmb:
        indices = {**indices, "utmb": live_utmb}

    # 2. Optimise images
    print("Optimising images...")
    optimize_images()

    # 3. Build gallery HTML
    print("Building gallery...")
    gallery_html = build_gallery_html()

    # 4. Fetch race data from Dropbox Excel
    print("Fetching race data from Dropbox Excel...")
    raw_sheets = fetch_excel_sheets(DROPBOX_XLSX_URL)
    sheets_data = {}
    for sheet_name, rows in raw_sheets.items():
        past, upcoming = parse_race_rows(rows)
        sheets_data[sheet_name] = (past, upcoming)
        print(f"  '{sheet_name}' → {len(past)} past, {len(upcoming)} upcoming")

    # 5. Build race tabs/panels and calendar
    if sheets_data:
        race_tabs_and_panels, calendar_cards, calendar_year = build_race_tabs_and_panels(sheets_data)
    else:
        # Fallback placeholder when Dropbox fetch fails
        race_tabs_and_panels = (
            f'<div class="year-tabs reveal"><div class="year-tab active" data-year="{CURRENT_YEAR}">{CURRENT_YEAR}</div></div>\n'
            f'<div class="year-panel active" id="panel-{CURRENT_YEAR}">'
            '<p style="color:var(--grey-mid);padding:2rem 0">Race data temporarily unavailable — check back soon.</p>'
            '</div>'
        )
        calendar_cards = '<p style="color:var(--grey-mid)">Race calendar temporarily unavailable — check back soon.</p>'
        calendar_year = CURRENT_YEAR

    # 6. Build SEO and analytics tags
    seo_tags = build_seo_tags(site, content.get("social", {}))
    analytics_tags = build_analytics_tags(content.get("analytics", {}))

    # 7. Render template
    print("Rendering template...")
    env = Environment(loader=FileSystemLoader(str(BUILD_DIR)), autoescape=False)
    tmpl = env.get_template("template.html")

    rendered = tmpl.render(
        site=site,
        hero=content.get("hero", {}),
        about=content.get("about", {}),
        values=content.get("values", []),
        mission=content.get("mission", {}),
        indices=indices,
        contact=content.get("contact", {}),
        social=content.get("social", {}),
        pdf=content.get("pdf", {"enabled": False}),
        footer=content.get("footer", {}),
        seo_tags=seo_tags,
        analytics_tags=analytics_tags,
        race_tabs_and_panels=race_tabs_and_panels,
        calendar_cards=calendar_cards,
        calendar_year=calendar_year,
        gallery_items=gallery_html,
    )

    # 8. Write output files
    out_html = ROOT / "index.html"
    out_html.write_text(rendered, encoding="utf-8")
    print(f"  ✓ index.html written ({len(rendered) // 1024} KB)")

    out_sitemap = ROOT / "sitemap.xml"
    out_sitemap.write_text(build_sitemap(base_url), encoding="utf-8")
    print("  ✓ sitemap.xml written")

    out_robots = ROOT / "robots.txt"
    out_robots.write_text(build_robots(base_url), encoding="utf-8")
    print("  ✓ robots.txt written")

    print("\n✓ Build complete.")


if __name__ == "__main__":
    main()
