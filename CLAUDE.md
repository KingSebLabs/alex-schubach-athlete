# Alex Schubach Athlete — Claude Notes

## Build
- `python3 build/build.py` — rebuilds `index.html`, `sitemap.xml`, `robots.txt` (use `python3`, not `python`)
- No test suite — a clean build is the verification step
- `index.html`, `sitemap.xml`, `robots.txt`, `races.json` are **generated** — never hand-edit them
- `races.json` — machine-readable race-day feed (`[{date: "YYYY-MM-DD", name}]`, one entry per race day; multi-day sheet ranges expand, TBC dates skipped; NOT rewritten when the Dropbox fetch fails). Consumed by alex-analytics-dashboard (issue #3 race-day annotations). It is listed in both workflows' `git add` lines — keep it there or the feed silently stops updating

## Remote main
- Remote `main` receives daily auto-build commits: `Auto-build: daily refresh from Dropbox Excel`
- When merging a feature branch, expect conflicts in `index.html`/`sitemap.xml` — resolve by rebuilding: `git checkout <feature> -- index.html sitemap.xml && python3 build/build.py`
- Push conflict resolution: `python3 build/build.py && git add index.html sitemap.xml robots.txt && GIT_EDITOR=true git rebase --continue && git push origin main`

## Deployment
- **GitHub Pages** serves the repo as static files: `CNAME` = `alexschubach.com`, `.nojekyll` present (no Jekyll processing)
- The auto-build commits on `main` come from two workflows in `.github/workflows/`:
  - `build-scheduled.yml` — daily cron `0 1 * * *` (1am UTC / 10am JST) + manual `workflow_dispatch`; pulls fresh race data from the Dropbox Excel, rebuilds, commits `Auto-build: daily refresh from Dropbox Excel [skip ci]`
  - `build-on-push.yml` — on push to `main`; rebuilds and commits `Auto-build: update site [skip ci]`
- Both workflows verify the build (title tag present, race cards present, output >100KB) before committing
- `.venv-build/` is a local Python venv for running the build — local convenience only, not part of deployment

## SEO
- All meta/OG/Twitter/JSON-LD tags are built in `build_seo_tags()` in `build.py`
- `site.title` and `site.description` in `content.yaml` flow into `<title>`, meta description, OG, and Twitter card automatically
- JSON-LD Person schema lives in `build_seo_tags()` — add `alternateName`, `sameAs` etc. there

## Design workflow
- Show design changes in `docs/*.html` demo files before applying to `build/template.html`

## HTML escaping contract in build.py
- `_fmt_narrative(text)` does **not** HTML-escape its input — callers must pass already-escaped text
- `_fmt_rich_cell(cell)` outputs pre-escaped HTML (safe to embed directly); includes `<strong>` and `<br>` tags
- For columns not in `RICH_TEXT_COLS`, escape at render time: `_fmt_narrative(html.escape(value))`
- `RICH_TEXT_COLS` values are passed through `_fmt_narrative` a second time at render in `build_race_card_html` — this is a known double-process (harmless, tracked as follow-up)

## SVG & logo assets
- `images/logo.svg` is the loading screen logo (Canva export); letter fills use `#f5f3f0` (not black) for dark background
- Bolt shape is defined once as `<symbol id="bolt">` in a hidden `<svg><defs>` block immediately after `<body>`, referenced via `<use href="#bolt">` in both the loader and nav
- Canva exports bolt as `#ff751f` — always normalise to site accent `#e8490f`
- To animate only part of an inline SVG (e.g. bolt-only pulse), embed SVG inline (not `<img>`) and apply the animation class to the specific `<g>`, not the wrapper
- Inline SVG clip-path IDs must be unique in the document — prefix loader IDs (e.g. `ll-bolt1`) to avoid collisions with other embedded SVGs

## CSS specificity gotcha
- `.nav-links a` (0,1,1) overrides `.nav-cta` (0,1,0) — use `.nav-links .nav-cta` to reliably override nav CTA colours

## Content
- Social links live in `content.yaml` under `social:` — not in `template.html`
- Content map — additional pages beyond `index.md`/`profile.md`/`results.md`/`values.md`/`mission.md`: `gallery.md`, `calendar.md`, `media-kit.md`, `partnerships.md`, `llms.txt`, `downloads/` (lead-magnet PDFs + media-kit PDF), `sponsor-and-partnership-media-kit.html` (generated, committed by the build workflows)
- Homepage flow since the 2026-06-28 restructure (current state): **Connect sits above Testimonials**

## CSS quirk
- `.cal-modal.open` and the gallery lightbox use `pointer-events: all` (non-standard but intentional) — don't change to `auto`
