# Race Website Improvements — Design Spec
**Date:** 2026-03-23
**Status:** Approved

---

## Context

The alex-schubach-athlete website pulls race data from a Dropbox Excel file and renders a static single-page site via a Python/Jinja2 build pipeline. Four UI improvements have been requested to improve the visual hierarchy of the results table, add rich text support for the expand section, surface race descriptions in more places, and give calendar visitors a way to read full race descriptions without the badge overflowing.

---

## Change 1 — Ranking Font Size

**Problem:** The Ranking column appears oversized. The base rule at `template.html` line ~284 sets `.race-h-pos { font-size: 0.95rem }` but a later "Fluid typography" override at line ~562 sets `.race-h-pos { font-size: clamp(1rem, 3vw, 1.4rem) }` — this cascades after the base rule and is the effective value at all viewport widths. At desktop it renders at up to 1.4rem, far larger than the Time column.

**Solution:**
1. Delete the fluid typography override at line ~562: remove `.race-h-pos { font-size: clamp(1rem, 3vw, 1.4rem); }` entirely
2. The base rule at line ~284 already sets `.race-h-pos { font-size: 0.95rem }` — same as `.race-h-time { font-size: 0.95rem }` — so no change needed there
3. The mobile override at line ~329: `.race-h-pos { font-size: 0.72rem }` remains unchanged

**Files changed:** `build/template.html`

---

## Change 2 — Excel Bold → White Text in Expand Section

**Problem:** `fetch_excel_sheets` uses `ws.iter_rows(values_only=True)` which strips all cell formatting — native Excel bold (Ctrl+B) in `COMMENTS PRE` / `COMMENTS POST` columns is discarded. The `_fmt_narrative` function only converts `**markdown**` syntax, not native Excel bold.

**Solution:**

### Step A — Load with rich text support
Change `openpyxl.load_workbook(..., data_only=True)` to `openpyxl.load_workbook(..., data_only=True, rich_text=True)`.

### Step B — Switch from values_only to Cell objects
Change `ws.iter_rows(values_only=True)` to `ws.iter_rows()` (returns rows of Cell objects).

This affects three places in `fetch_excel_sheets` that currently assume plain Python values:
- **Header detection** (line ~87): `any(c for c in r)` → `any(c.value for c in r)`
- **Header extraction** (line ~91): `str(c).strip() if c else ""` → `str(c.value).strip() if c.value else ""`
- **Row filter** (line ~95): `if any(v for v in row)` → `if any(cell.value for cell in row)`
- **Dict comprehension** (line ~93): `_fmt_cell(v)` → handled per-column (see Step C)

### Step C — Add `_fmt_rich_cell` for narrative columns
Add a new function:

```python
RICH_TEXT_COLS = {
    "COMMENTS PRE", "COMMENTS POST", "GOING IN", "LOOKING BACK",
    "PRE RACE", "POST RACE"
}

def _fmt_rich_cell(cell) -> str:
    """Convert cell to HTML, preserving bold as <strong> for narrative columns."""
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
                # Plain str elements within CellRichText have no .font attribute
                parts.append(str(block))
        return "".join(parts).replace('\n', '<br>')
    # Plain string: pass through _fmt_narrative to keep **markdown** bold and \n→<br>
    return _fmt_narrative(str(v)) if v else ""
```

Note: `CellRichText` can contain bare `str` elements (no font object). The `isinstance(block, TextBlock)` guard is required before accessing `block.font`.

Update the dict comprehension to use `_fmt_rich_cell` for narrative columns and `_fmt_cell(cell.value)` for all others:

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

**CSS already in place:** `.race-narrative p strong { color: var(--text-light); font-weight: 600; }` — no CSS changes needed.

**Verification:** Test with a cell containing mixed bold and plain text in the same cell (e.g., "Feeling `**strong**` going in") — confirm only the bold run is wrapped in `<strong>`. Also confirm that date/time/numeric columns in the results table still render correctly after the `iter_rows` change.

**Files changed:** `build/build.py`

---

## Change 3 — Race Description in Expand Section

**Problem:** The expand section shows only "Going In" and "Looking Back". `RACE DESCRIPTION` data exists but is only shown (truncated) in the calendar badge. The description is also hard-truncated to 140 chars in Python, which limits what the modal and expand section can show.

**Solution:**

### Step A — Remove Python truncation
Change line ~206: `description = find_col(row, "RACE DESCRIPTION", "DESCRIPTION")[:140]` → `find_col(row, "RACE DESCRIPTION", "DESCRIPTION")`. The badge's CSS `-webkit-line-clamp: 2` already handles visual truncation.

### Step B — Add description column to expand body
In `build_race_card_html`, when `race["description"]` is non-empty, prepend a Race Description narrative column **before** Going In and Looking Back.

The description column uses the same markup pattern as the other narratives:
```html
<div class="race-narrative">
  <div class="race-narrative-label">Race Description</div>
  <p>{race["description"]}</p>
</div>
```

Apply `_fmt_narrative` to the description text (for `\n → <br>` handling).

When description is present, add class `has-desc` to `.race-body-inner`. When absent, omit this class and the expand body remains 2-column as before.

### Step C — CSS: 3-column grid
Add to `template.html`:
```css
.race-body-inner.has-desc { grid-template-columns: 1fr 1fr 1fr; }
```

Also increase `max-height` on `.race-item.open .race-body` from `2000px` to `3000px` to prevent clipping when all three columns have substantial content.

The existing `@media (max-width: 768px)` rule already sets `.race-body-inner { grid-template-columns: 1fr }` — this overrides `has-desc` on mobile, so all columns stack naturally.

**Column order (left → right):** Race Description → Going In → Looking Back

**Files changed:** `build/build.py`, `build/template.html`

---

## Change 4 — "Read More" Modal for Calendar Badges

**Problem:** The `RACE DESCRIPTION` text in upcoming race badges is clamped to 2 lines. Visitors have no way to read the full description.

**Solution:** Add a modal overlay (Option A) — identical in pattern to the existing gallery lightbox — triggered by a "Read more →" button on each calendar badge that has a description.

### Python (build.py) — `build_calendar_card_html`
When `race["description"]` is non-empty:
1. Add data attributes to `.cal-card` using `html.escape()` on each value:
   ```python
   import html
   data_attrs = (
       f'data-desc="{html.escape(race["description"])}" '
       f'data-race="{html.escape(race["name"].upper())}" '
       f'data-date="{html.escape(race["date"])}" '
       f'data-details="{html.escape(details)}"'
   )
   ```
2. Add a "Read more →" button inside the card:
   ```html
   <button class="cal-read-more" onclick="openCalModal(this)">Read more →</button>
   ```

### HTML (template.html)
Add a `<div class="cal-modal" id="cal-modal" aria-hidden="true">` overlay containing:
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

### CSS
```css
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
  text-align: right; width: 100%;
  transition: opacity 0.2s;
}
.cal-read-more:hover { opacity: 0.75; }
@media (max-width: 640px) {
  .cal-modal-card { padding: 2rem 1.5rem; width: 95vw; }
  .cal-modal-text { font-size: 0.92rem; }
  .cal-modal-close { top: 0.75rem; right: 1rem; font-size: 1.6rem; }
}
```

### JavaScript
```javascript
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
    // Use innerHTML (not textContent) so _fmt_narrative <br> tags render as line breaks
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

  // Exposed for inline onclick. This script must NOT be deferred or declared
  // as a module — the inline onclick attribute requires window.openCalModal
  // to be defined at the time the button is clicked.
  window.openCalModal = openCalModal;

  modal.querySelector('.cal-modal-close').addEventListener('click', closeCalModal);
  modal.addEventListener('click', function(e) { if (e.target === modal) closeCalModal(); });
  document.addEventListener('keydown', function(e) {
    // Guard: only handle when this modal is open
    if (!modal.classList.contains('open')) return;
    if (e.key === 'Escape') closeCalModal();
  });
})();
```

Note: Focus is moved to the close button on open and returned to the triggering button on close, satisfying WCAG 2.1 AA focus-management requirements for modal dialogs.

**Files changed:** `build/build.py`, `build/template.html`

---

## Verification

1. Run `python build/build.py` — confirm `index.html` regenerates without errors
2. Open `index.html` in a browser and confirm:
   - **Change 1:** Ranking column is visibly smaller than the Time column at all viewport widths (desktop, tablet, mobile)
   - **Change 2:** Add a cell to `COMMENTS PRE` or `COMMENTS POST` with **mixed** bold and plain text in the same cell (e.g., "Feeling strong going into this one") where only "strong" is bolded → rebuild → confirm only that word appears white in the expand section. Also confirm date/time/numeric result columns still render correctly.
   - **Change 3:** A race with a description shows Race Description as the leftmost column in the expand body; races without a description still show the 2-column Going In / Looking Back layout
   - **Change 4:** Calendar badges with a description show "Read more →"; clicking opens the modal with full text; × button, backdrop click, and Escape all close it; `aria-hidden` toggles correctly
3. Check mobile at 375px width:
   - Ranking text remains readable
   - Expand body stacks to single column (description, then going in, then looking back)
   - Modal card is full-width (95vw) with adequate font size and tap target on the close button
