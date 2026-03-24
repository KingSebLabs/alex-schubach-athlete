# Race Website Improvements Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix ranking font size, add Excel native bold → white text in expand section, add race description to expand section, and add a "Read more" modal to calendar badges.

**Architecture:** All changes are in two files — `build/build.py` (Python data pipeline + HTML generation) and `build/template.html` (CSS + JS + Jinja2 template). Running `python build/build.py` regenerates `index.html`. Changes are independent and can be applied in order; each task ends with a build + visual verification step and a commit.

**Tech Stack:** Python 3, openpyxl (Excel parsing with `rich_text=True`), Jinja2 (templating), vanilla JS, CSS Grid

---

## File Map

| File | Changes |
|------|---------|
| `build/template.html` | Task 1: delete line ~562 `.race-h-pos` clamp override; Task 3: add `.race-body-inner.has-desc` CSS + bump `max-height`; Task 4: add `.cal-modal` HTML + CSS |
| `build/build.py` | Task 2: add `RICH_TEXT_COLS`, `_fmt_rich_cell()`, update `fetch_excel_sheets`; Task 3: remove 140-char truncation, update `build_race_card_html`; Task 4: update `build_calendar_card_html`, add JS block |

---

## Task 1: Fix Ranking Font Size

**Files:**
- Modify: `build/template.html` line ~562

The ranking column currently renders much larger than the time column because a "Fluid typography" block at line ~562 overrides the base rule with `clamp(1rem, 3vw, 1.4rem)`. The fix is to delete that one override line — the base rule at line ~284 already sets `font-size: 0.95rem`, matching the Time column exactly.

- [ ] **Step 1: Open `build/template.html` and find line ~562**

Search for:
```css
.race-h-pos      { font-size: clamp(1rem, 3vw, 1.4rem); }
```
It sits inside a `/* Fluid typography */` comment block alongside `.value-title`, `.value-num`, `.stat-number`, `.race-h-sub`.

- [ ] **Step 2: Delete that single line**

Remove only `.race-h-pos { font-size: clamp(1rem, 3vw, 1.4rem); }`. Leave all adjacent rules untouched.

- [ ] **Step 3: Rebuild and verify**

```bash
cd /Users/kingseb/Documents/GitHub/alex-schubach-athlete
python build/build.py
open index.html
```

Expected: in the race results table, the Ranking column text is the same size as the Time column at desktop width. On mobile (≤768px) the existing `0.72rem` override kicks in — both Ranking and Time are smaller, which is expected.

- [ ] **Step 4: Commit**

```bash
git add build/template.html
git commit -m "fix: remove fluid typography override making ranking text oversized"
```

---

## Task 2: Excel Native Bold → White Text in Expand Section

**Files:**
- Modify: `build/build.py`

The expand section's "Going In" and "Looking Back" columns should render any natively-bolded Excel text (Ctrl+B) as white. Currently `fetch_excel_sheets` reads with `values_only=True` which strips all formatting. This task adds rich-text-aware reading for narrative columns.

- [ ] **Step 1: Add `RICH_TEXT_COLS` constant near the top of `build.py`**

Place it just above the `_fmt_narrative` function (around line 60):

```python
# Columns whose native Excel bold formatting should render as <strong> in HTML
RICH_TEXT_COLS = {
    "COMMENTS PRE", "COMMENTS POST", "GOING IN", "LOOKING BACK",
    "PRE RACE", "POST RACE"
}
```

- [ ] **Step 2: Add `_fmt_rich_cell` function directly below `_fmt_narrative`**

```python
def _fmt_rich_cell(cell) -> str:
    """Convert a Cell to HTML, preserving native Excel bold as <strong>.

    openpyxl returns a CellRichText object when the cell contains inline
    formatting (e.g. some words bolded). Elements in that object can be
    either TextBlock (has .font) or plain str (no .font). We must guard
    with isinstance before accessing .font.
    """
    from openpyxl.cell.rich_text import CellRichText, TextBlock
    v = cell.value
    if v is None:
        return ""
    if isinstance(v, CellRichText):
        parts = []
        for block in v:
            if isinstance(block, TextBlock):
                text = str(block.text)
                if block.font and getattr(block.font, 'b', False):
                    parts.append(f"<strong>{text}</strong>")
                else:
                    parts.append(text)
            else:
                # Bare str element inside CellRichText — no .font attribute
                parts.append(str(block))
        return "".join(parts).replace('\n', '<br>')
    # Plain string fallback: use _fmt_narrative to keep **markdown** bold and \n→<br>
    return _fmt_narrative(str(v)) if v else ""
```

- [ ] **Step 3: Update `load_workbook` call in `fetch_excel_sheets` to enable rich text**

Find (line ~76):
```python
wb = openpyxl.load_workbook(io.BytesIO(resp.content), data_only=True)
```
Change to:
```python
wb = openpyxl.load_workbook(io.BytesIO(resp.content), data_only=True, rich_text=True)
```

- [ ] **Step 4: Switch `iter_rows` from `values_only=True` to Cell objects**

Find (line ~82):
```python
rows = list(ws.iter_rows(values_only=True))
```
Change to:
```python
rows = list(ws.iter_rows())
```

- [ ] **Step 5: Update all three places that assume plain Python values in the row loop**

**Header detection** (line ~87) — find:
```python
header_idx = next((i for i, r in enumerate(rows) if any(c for c in r)), None)
```
Change to:
```python
header_idx = next((i for i, r in enumerate(rows) if any(c.value for c in r)), None)
```

**Header extraction** (line ~91) — find:
```python
headers = [str(c).strip() if c else "" for c in rows[header_idx]]
```
Change to:
```python
headers = [str(c.value).strip() if c.value else "" for c in rows[header_idx]]
```

**Row filter** (line ~95) — find:
```python
if any(v for v in row)
```
Change to:
```python
if any(cell.value for cell in row)
```

- [ ] **Step 6: Update the dict comprehension to route narrative columns through `_fmt_rich_cell`**

Find (line ~93):
```python
{headers[i]: (_fmt_cell(v)) for i, v in enumerate(row) if i < len(headers)}
```
Change to:
```python
{
    headers[i]: (
        _fmt_rich_cell(cell)
        if headers[i].strip().upper() in RICH_TEXT_COLS
        else _fmt_cell(cell.value)
    )
    for i, cell in enumerate(row)
    if i < len(headers)
}
```

- [ ] **Step 7: Rebuild and verify**

```bash
python build/build.py
open index.html
```

Expected:
- All existing race results still render correctly (dates, times, positions, names unchanged)
- If you have a race with bold text in COMMENTS PRE or COMMENTS POST: expand that race row and confirm the bolded word(s) appear in white (`var(--text-light)` / `#f0ede8`) while surrounding text stays grey
- To verify the native bold path (the real feature): open the Excel file, select a word inside a COMMENTS PRE or COMMENTS POST cell, press Ctrl+B (native Excel bold), save, re-run `python build/build.py`, and confirm that word appears white in the expand section. Adding `**text**` markdown only tests the fallback path — not the same thing

- [ ] **Step 8: Commit**

```bash
git add build/build.py
git commit -m "feat: read native Excel bold from narrative cells and render as white <strong> text"
```

---

## Task 3: Race Description Column in Expand Section

**Files:**
- Modify: `build/build.py` (lines ~206, ~294–340)
- Modify: `build/template.html` (lines ~298, ~301)

Add Race Description as the leftmost column in the expand body. Also remove the Python 140-char truncation — CSS already clamps the badge display.

- [ ] **Step 1: Remove the 140-char truncation in `parse_race_rows`**

Find (line ~206):
```python
description = find_col(row, "RACE DESCRIPTION", "DESCRIPTION")[:140]
```
Change to:
```python
description = find_col(row, "RACE DESCRIPTION", "DESCRIPTION")
```

- [ ] **Step 2: Add the description column to `build_race_card_html`**

In `build_race_card_html` (around line 305), the function builds `body_parts`. Add the description block at the start, before the Going In block:

```python
body_parts = []
if race.get("description"):
    body_parts.append(
        f'              <div class="race-narrative">\n'
        f'                <div class="race-narrative-label">Race Description</div>\n'
        f'                <p>{_fmt_narrative(race["description"])}</p>\n'
        f'              </div>'
    )
if race["comments_pre"]:
    body_parts.append(
        f'              <div class="race-narrative">\n'
        f'                <div class="race-narrative-label">Going In</div>\n'
        f'                <p>{_fmt_narrative(race["comments_pre"])}</p>\n'
        f'              </div>'
    )
if race["comments_post"]:
    body_parts.append(
        f'              <div class="race-narrative">\n'
        f'                <div class="race-narrative-label">Looking Back</div>\n'
        f'                <p>{_fmt_narrative(race["comments_post"])}</p>\n'
        f'              </div>'
    )
```

- [ ] **Step 3: Add `has-desc` class to `.race-body-inner` when description is present**

Find the return block in `build_race_card_html` (line ~335):
```python
          <div class="race-body">
            <div class="race-body-inner">
```
Change to use a conditional class:
```python
has_desc = "has-desc" if race.get("description") else ""
```
And in the f-string:
```python
          <div class="race-body">
            <div class="race-body-inner {has_desc}">
```

- [ ] **Step 4: Add 3-column CSS and increase `max-height` in `template.html`**

Find (line ~298–301):
```css
.race-item.open .race-body { max-height: 2000px; }
.race-body-inner {
  padding: 2.5rem 2rem 2.5rem 2rem;
  display: grid; grid-template-columns: 1fr 1fr; gap: 2.5rem;
}
```
Change to:
```css
.race-item.open .race-body { max-height: 3000px; }
.race-body-inner {
  padding: 2.5rem 2rem 2.5rem 2rem;
  display: grid; grid-template-columns: 1fr 1fr; gap: 2.5rem;
}
.race-body-inner.has-desc { grid-template-columns: 1fr 1fr 1fr; }
```

- [ ] **Step 5: Rebuild and verify**

```bash
python build/build.py
open index.html
```

Expected:
- A race that has a RACE DESCRIPTION value: expand row shows three columns — Race Description (left), Going In (middle), Looking Back (right)
- A race without a description: expand row still shows two columns — Going In and Looking Back only
- On mobile (375px): all columns stack vertically, description first
- Badge description text is still clamped to 2 lines in the calendar (CSS clamp unchanged)

- [ ] **Step 6: Commit**

```bash
git add build/build.py build/template.html
git commit -m "feat: add race description as first column in expand section, remove 140-char truncation"
```

---

## Task 4: "Read More" Modal for Calendar Badges

**Files:**
- Modify: `build/build.py` — `build_calendar_card_html`
- Modify: `build/template.html` — add modal HTML, CSS, JS block

Add a lightbox-style modal triggered by a "Read more →" button on calendar badges that have a description.

- [ ] **Step 1: Add `import html` at the top of `build.py`**

Find the existing imports near the top of `build/build.py` and add:
```python
import html
```
(It's a Python stdlib module — no installation needed.)

- [ ] **Step 2: Update `build_calendar_card_html` to add data attributes and button**

Replace the current function body in `build_calendar_card_html` (lines ~343–358):

```python
def build_calendar_card_html(race: dict) -> str:
    """Build a calendar card for an upcoming race."""
    tbc = "tbc" in race.get("registered", "").lower()
    tbc_badge = '<span class="cal-tbc">TBC</span>' if tbc else ""
    detail_parts = [p for p in [race.get("type"), race.get("distance"), race.get("location")] if p and p != "—"]
    details = " · ".join(detail_parts)

    desc = race.get("description", "")
    if desc:
        desc_html = f'        <div class="cal-desc">{desc}</div>\n'
        data_attrs = (
            f' data-desc="{html.escape(desc)}"'
            f' data-race="{html.escape(race["name"].upper())}"'
            f' data-date="{html.escape(race["date"])}"'
            f' data-details="{html.escape(details)}"'
        )
        read_more_html = '        <button class="cal-read-more" onclick="openCalModal(this)">Read more →</button>\n'
    else:
        desc_html = ""
        data_attrs = ""
        read_more_html = ""

    return (
        f'      <div class="cal-card reveal"{data_attrs}>\n'
        f'        <div class="cal-month">{race["date"]} {tbc_badge}</div>\n'
        f'        <div class="cal-race">{race["name"].upper()}</div>\n'
        f'        <div class="cal-details">{details}</div>\n'
        f'{desc_html}'
        f'{read_more_html}'
        f'      </div>'
    )
```

- [ ] **Step 3: Add modal HTML to `template.html`**

Find the existing `<div class="lightbox" id="lightbox" ...>` block (around line ~1028). Add the calendar modal immediately after the closing `</div>` of the lightbox:

```html
<div class="cal-modal" id="cal-modal" aria-hidden="true">
  <div class="cal-modal-card">
    <button class="cal-modal-close" aria-label="Close">×</button>
    <div class="cal-modal-month"></div>
    <div class="cal-modal-race"></div>
    <div class="cal-modal-details"></div>
    <div class="cal-modal-label">Race Description</div>
    <div class="cal-modal-text"></div>
  </div>
</div>
```

- [ ] **Step 4: Add modal CSS to `template.html`**

Find the `/* Lightbox */` CSS block (around line ~405). Add the calendar modal CSS immediately after the lightbox block ends:

```css
/* Calendar modal */
.cal-modal {
  position: fixed; inset: 0; z-index: 9000;
  background: rgba(0,0,0,0.92);
  display: flex; align-items: center; justify-content: center;
  opacity: 0; pointer-events: none; transition: opacity 0.3s;
}
.cal-modal.open { opacity: 1; pointer-events: all; }
.cal-modal-card {
  background: #1c1c1b;
  border: 1px solid rgba(232,73,15,0.3);
  padding: 2.5rem;
  max-width: 520px; width: 90vw;
  position: relative;
  transform: translateY(16px); transition: transform 0.3s;
}
.cal-modal.open .cal-modal-card { transform: translateY(0); }
.cal-modal-close {
  position: absolute; top: 1rem; right: 1.25rem;
  background: none; border: none;
  color: var(--grey-mid); font-size: 1.4rem;
  cursor: pointer; line-height: 1; transition: color 0.2s;
}
.cal-modal-close:hover { color: var(--text-light); }
.cal-modal-month {
  font-size: 0.6rem; font-weight: 700; letter-spacing: 0.25em;
  text-transform: uppercase; color: var(--accent); margin-bottom: 0.75rem;
}
.cal-modal-race {
  font-family: var(--font-display); font-size: 1.8rem;
  letter-spacing: 0.04em; margin-bottom: 0.4rem;
}
.cal-modal-details {
  font-size: 0.75rem; color: var(--grey-mid);
  margin-bottom: 1.25rem; line-height: 1.6;
}
.cal-modal-label {
  font-size: 0.55rem; font-weight: 700; letter-spacing: 0.25em;
  text-transform: uppercase; color: var(--accent); margin-bottom: 0.5rem;
  display: flex; align-items: center; gap: 0.4rem;
}
.cal-modal-label::before { content: ''; width: 12px; height: 2px; background: var(--accent); }
.cal-modal-text {
  font-size: 0.88rem; color: var(--grey-mid); line-height: 1.75;
}
.cal-read-more {
  display: block; background: none; border: none;
  color: var(--accent); font-size: 0.6rem; font-weight: 700;
  letter-spacing: 0.18em; text-transform: uppercase;
  cursor: pointer; padding: 0; margin-top: 0.75rem;
  text-align: right; width: 100%; transition: opacity 0.2s;
}
.cal-read-more:hover { opacity: 0.75; }
@media (max-width: 640px) {
  .cal-modal-card { padding: 2rem 1.5rem; width: 95vw; }
  .cal-modal-text { font-size: 0.92rem; }
  .cal-modal-close { top: 0.75rem; right: 1rem; font-size: 1.6rem; }
}
```

- [ ] **Step 5: Add modal JavaScript to `template.html`**

Find the closing `})();` of the existing gallery lightbox IIFE (around line ~1073). Add the calendar modal script block immediately after it:

```html
<script>
(function() {
  const modal = document.getElementById('cal-modal');
  if (!modal) return;

  let lastTrigger = null;

  function openCalModal(btn) {
    lastTrigger = btn;
    const card = btn.closest('.cal-card');
    modal.querySelector('.cal-modal-month').textContent = card.dataset.date || '';
    modal.querySelector('.cal-modal-race').textContent = card.dataset.race || '';
    modal.querySelector('.cal-modal-details').textContent = card.dataset.details || '';
    // innerHTML so any <br> tags from _fmt_narrative render as line breaks
    modal.querySelector('.cal-modal-text').innerHTML = card.dataset.desc || '';
    modal.classList.add('open');
    modal.setAttribute('aria-hidden', 'false');
    document.body.style.overflow = 'hidden';
    modal.querySelector('.cal-modal-close').focus();
  }

  function closeCalModal() {
    modal.classList.remove('open');
    modal.setAttribute('aria-hidden', 'true');
    document.body.style.overflow = '';
    if (lastTrigger) { lastTrigger.focus(); lastTrigger = null; }
  }

  // Must be on window — inline onclick="openCalModal(this)" needs global access.
  // Do NOT defer this script or declare it as a module.
  window.openCalModal = openCalModal;

  modal.querySelector('.cal-modal-close').addEventListener('click', closeCalModal);
  modal.addEventListener('click', function(e) { if (e.target === modal) closeCalModal(); });
  document.addEventListener('keydown', function(e) {
    if (!modal.classList.contains('open')) return;
    if (e.key === 'Escape') closeCalModal();
  });
})();
</script>
```

- [ ] **Step 6: Rebuild and verify**

```bash
python build/build.py
open index.html
```

Expected:
- Calendar badges with a RACE DESCRIPTION show the clamped preview text AND a "Read more →" button aligned to the right
- Clicking "Read more →" opens the modal: dark overlay, card slides up, shows race name + date + details + full description
- Clicking × closes the modal and focus returns to the "Read more →" button
- Clicking the dark backdrop closes the modal
- Pressing Escape closes the modal
- Badges without a description show no button and have no data attributes
- On mobile (375px): modal card is 95vw wide, text is readable, close button tap target is large

- [ ] **Step 7: Commit**

```bash
git add build/build.py build/template.html
git commit -m "feat: add read more modal to calendar badges with full race description"
```

---

## Final Verification

```bash
python build/build.py
open index.html
```

Walk through all four changes end-to-end:
1. Race results table — Ranking column matches Time column size at desktop
2. Expand a race with bold text in comments — bold words appear white
3. Expand a race with a description — three columns appear; expand a race without — two columns
4. Calendar section — badges with descriptions have "Read more →"; modal opens/closes correctly on desktop and mobile
