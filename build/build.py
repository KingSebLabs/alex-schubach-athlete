"""
build.py
--------
Builds index.html, sitemap.xml, and robots.txt from:
  - build/template.html        (Jinja2 HTML template)
  - content.yaml               (editable site content)
  - Google Sheets (live)       (race results + calendar)
  - images/gallery/            (photo files)

Usage:
  python3 build/build.py

Environment variable (optional, for private sheets):
  SHEETS_URL_OVERRIDE   — if set, uses this URL instead of config
"""

import os
import sys
import csv
import io
import re
import datetime
import urllib.request
from pathlib import Path

import yaml
from jinja2 import Environment, FileSystemLoader, Undefined
from PIL import Image

# ─── Paths ───────────────────────────────────────────────────────────────────
ROOT = Path(__file__).parent.parent
BUILD_DIR = ROOT / "build"
IMAGES_DIR = ROOT / "images"
GALLERY_DIR = IMAGES_DIR / "gallery"

# ─── Google Sheets config ─────────────────────────────────────────────────────
# Paste your Google Sheet ID here (from the URL: /spreadsheets/d/SHEET_ID/edit)
SPREADSHEET_ID = "YOUR_SPREADSHEET_ID_HERE"

# Sheet GIDs — find them in the URL when you click each tab (?gid=NNNNNN)
# Update these with the actual GIDs from your sheet's URL
SHEET_GIDS = {
    "Races 25": "0",          # Update with actual GID
    "Races 26": "123456789",  # Update with actual GID
    # Add "Races 27": "GID" when you create that sheet
}

# The name of the most recent year tab (controls which is shown as active by default)
CURRENT_YEAR = "26"


def fetch_sheet_csv(spreadsheet_id: str, gid: str) -> list[dict]:
    """Fetch a Google Sheet tab as CSV and return list of row dicts."""
    url = f"https://docs.google.com/spreadsheets/d/{spreadsheet_id}/export?format=csv&gid={gid}"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            raw = resp.read().decode("utf-8")
        reader = csv.DictReader(io.StringIO(raw))
        return list(reader)
    except Exception as e:
        print(f"  ⚠ Could not fetch sheet GID={gid}: {e}", file=sys.stderr)
        return []


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
    for img in images:
        # Use filename (without extension) as alt text, replacing _ with space
        alt = img.stem.lstrip("0123456789").strip("_- ").replace("_", " ").title()
        items.append(
            f'      <div class="gallery-item reveal">'
            f'<img src="images/gallery/{img.name}" alt="{alt}" style="width:100%;height:100%;object-fit:cover;"></div>'
        )
    return "\n".join(items)


# ─── Excel/Sheets column name helpers ────────────────────────────────────────

def find_col(row: dict, *candidates) -> str:
    """Find first matching column key (case-insensitive, strips whitespace)."""
    keys_lower = {k.strip().lower(): k for k in row.keys()}
    for candidate in candidates:
        if candidate.lower() in keys_lower:
            return row[keys_lower[candidate.lower()]].strip()
    return ""


def parse_race_rows(rows: list[dict]) -> tuple[list[dict], list[dict]]:
    """
    Split sheet rows into (past_races, upcoming_races).
    A row is a past race if RACE RESULTS is non-empty.
    A row is upcoming if RACE RESULTS is empty but EVENT is non-empty.
    Filters to rows where REGISTERED contains 'Alex'.
    """
    past, upcoming = [], []
    for row in rows:
        event = find_col(row, "EVENT", "Event", "RACE", "Race")
        if not event or event.lower().startswith("event"):  # skip header rows
            continue
        registered = find_col(row, "REGISTERED", "Registered", "REGISTRATION")
        if registered and "alex" not in registered.lower():
            continue  # skip races not registered for Alex

        result = find_col(row, "RACE RESULTS", "Race Results", "RESULT", "Results", "TIME")
        date_str = find_col(row, "BLACKOUT DATES", "Blackout Dates", "DATE", "Date", "RACE DATE")
        comments_pre = find_col(row, "COMMENTS PRE", "Comments Pre", "PRE RACE", "GOING IN")
        comments_post = find_col(row, "COMMENTS POST", "Comments Post", "POST RACE", "LOOKING BACK")
        pos_overall = find_col(row, "POSITION OVERALL", "Position Overall", "OVERALL POSITION", "POS OVERALL")
        pos_ag = find_col(row, "POSITION AG", "Position AG", "AG POSITION", "AGE GROUP POS")

        # Parse race name (first line of EVENT cell)
        race_name = event.split("\n")[0].strip()
        # Try to get date from second line of EVENT or from BLACKOUT DATES
        race_date = date_str.split("\n")[0].strip() if date_str else ""
        # Try to infer distance/type from race name
        race_type = infer_race_type(race_name)

        entry = {
            "name": race_name,
            "date": race_date,
            "type": race_type,
            "result": result,
            "comments_pre": comments_pre,
            "comments_post": comments_post,
            "pos_overall": pos_overall,
            "pos_ag": pos_ag,
        }

        if result:
            past.append(entry)
        elif race_name:
            upcoming.append(entry)

    return past, upcoming


def infer_race_type(name: str) -> str:
    """Guess race type/distance from name."""
    n = name.lower()
    if "hyrox" in n:
        return "Hybrid"
    if "spartan" in n:
        return "OCR"
    if "marathon" in n and "half" not in n:
        return "42.2 km · Road"
    if "half marathon" in n or "half" in n:
        return "21.1 km · Road"
    if "10k" in n or "10km" in n:
        return "10 km · Road"
    if "5k" in n or "5km" in n:
        return "5 km · Road"
    if "ultra" in n or "80k" in n or "100k" in n:
        return "Ultra Trail"
    if "trail" in n or "mountain" in n or "fuji" in n or "nikko" in n:
        return "Trail"
    return "Road"


def build_race_card_html(race: dict) -> str:
    """Build a single collapsible race card."""
    name = race["name"]
    date = race["date"]
    result = race["result"]
    race_type = race["type"]
    pos = race["pos_overall"] or "—"
    pos_ag = race["pos_ag"]

    # Stats strip
    stat_items = []
    if race["pos_overall"]:
        stat_items.append(("Overall", race["pos_overall"]))
    if pos_ag:
        stat_items.append(("Age Group", pos_ag))
    stat_items.append(("Time", result))
    stat_items.append(("Format", race_type))

    stats_html = "\n".join(
        f'            <div class="race-stat-mini"><div class="race-stat-mini-label">{label}</div>'
        f'<div class="race-stat-mini-val">{val}</div></div>'
        for label, val in stat_items
    )

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
          <div class="race-header" onclick="toggleRace(this)">
            <div><div class="race-h-name">{name}</div><div class="race-h-sub">{date}</div></div>
            <div class="race-h-meta">{race_type}</div>
            <div class="race-h-time">{result}</div>
            <div class="race-h-position">{pos}</div>
            <div></div>
          </div>
          <div class="race-stats-strip">
{stats_html}
          </div>
          <div class="race-body">
            <div class="race-body-inner">
{body_html}
            </div>
          </div>
        </div>'''


def build_calendar_card_html(race: dict) -> str:
    """Build a calendar card for an upcoming race."""
    return (
        f'      <div class="cal-card reveal">\n'
        f'        <div class="cal-month">{race["date"]}</div>\n'
        f'        <div class="cal-race">{race["name"].upper()}</div>\n'
        f'        <div class="cal-details">{race["type"]}</div>\n'
        f'      </div>'
    )


def build_race_tabs_and_panels(sheets_data: dict[str, tuple]) -> tuple[str, str]:
    """
    Build the year-tabs + year-panels HTML from all sheets.
    sheets_data = { "Races 25": (past_races, upcoming), "Races 26": (past_races, upcoming), ... }
    Returns (tabs_and_panels_html, calendar_cards_html)
    """
    # Sort years ascending so tabs appear 2025 → 2026 → ...
    years = sorted(sheets_data.keys())

    tabs_html = '<div class="year-tabs reveal">\n'
    panels_html = ""
    all_upcoming = []

    for sheet_name in years:
        year_short = re.sub(r"[^0-9]", "", sheet_name)  # "Races 26" → "26"
        year_full = f"20{year_short}"
        past_races, upcoming_races = sheets_data[sheet_name]
        is_current = year_short == CURRENT_YEAR

        tabs_html += f'  <div class="year-tab{" active" if is_current else ""}" data-year="{year_full}">{year_full}</div>\n'

        race_cards = "\n".join(build_race_card_html(r) for r in past_races) if past_races else \
            '        <p style="color:var(--grey-mid);padding:2rem 0">No results recorded yet.</p>'

        panels_html += (
            f'\n    <div class="year-panel{" active" if is_current else ""}" id="panel-{year_full}">\n'
            f'      <div class="race-accordion">\n'
            f'{race_cards}\n'
            f'      </div>\n'
            f'    </div>'
        )

        all_upcoming.extend(upcoming_races)

    tabs_html += "</div>"

    calendar_html = "\n".join(build_calendar_card_html(r) for r in all_upcoming) if all_upcoming else \
        '      <p style="color:var(--grey-mid)">Calendar coming soon.</p>'

    calendar_year = f"20{CURRENT_YEAR}"

    return tabs_html + panels_html, calendar_html, calendar_year


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

    # 2. Optimise images
    print("Optimising images...")
    optimize_images()

    # 3. Build gallery HTML
    print("Building gallery...")
    gallery_html = build_gallery_html()

    # 4. Fetch Google Sheets data
    print("Fetching race data from Google Sheets...")
    sheets_data = {}
    if SPREADSHEET_ID == "YOUR_SPREADSHEET_ID_HERE":
        print("  ⚠ SPREADSHEET_ID not configured — skipping Sheets fetch")
        print("  → Update SPREADSHEET_ID and SHEET_GIDS in build/build.py")
        sheets_data = {}
    else:
        for sheet_name, gid in SHEET_GIDS.items():
            print(f"  Fetching '{sheet_name}'...")
            rows = fetch_sheet_csv(SPREADSHEET_ID, gid)
            if rows:
                past, upcoming = parse_race_rows(rows)
                sheets_data[sheet_name] = (past, upcoming)
                print(f"    → {len(past)} past races, {len(upcoming)} upcoming")

    # 5. Build race tabs/panels and calendar
    if sheets_data:
        race_tabs_and_panels, calendar_cards, calendar_year = build_race_tabs_and_panels(sheets_data)
    else:
        # Fallback: keep existing race content as a placeholder message
        race_tabs_and_panels = (
            '<div class="year-tabs reveal"><div class="year-tab active" data-year="2026">2026</div></div>\n'
            '<div class="year-panel active" id="panel-2026">'
            '<p style="color:var(--grey-mid);padding:2rem 0">Configure SPREADSHEET_ID in build/build.py to auto-populate race results.</p>'
            '</div>'
        )
        calendar_cards = '<p style="color:var(--grey-mid)">Configure SPREADSHEET_ID in build/build.py to auto-populate the calendar.</p>'
        calendar_year = f"20{CURRENT_YEAR}"

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
        indices=content.get("indices", {}),
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
    if SPREADSHEET_ID == "YOUR_SPREADSHEET_ID_HERE":
        print("\n⚠ Next step: open build/build.py and set SPREADSHEET_ID + SHEET_GIDS")


if __name__ == "__main__":
    main()
