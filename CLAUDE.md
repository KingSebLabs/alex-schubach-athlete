# Alex Schubach Athlete — Claude Notes

## Build
- `python3 build/build.py` — rebuilds `index.html`, `sitemap.xml`, `robots.txt` (use `python3`, not `python`)
- No test suite — a clean build is the verification step
- `index.html`, `sitemap.xml`, `robots.txt` are **generated** — never hand-edit them

## Remote main
- Remote `main` receives daily auto-build commits: `Auto-build: daily refresh from Dropbox Excel`
- When merging a feature branch, expect conflicts in `index.html`/`sitemap.xml` — resolve by rebuilding: `git checkout <feature> -- index.html sitemap.xml && python3 build/build.py`
- Push conflict resolution: `python3 build/build.py && git add index.html sitemap.xml robots.txt && GIT_EDITOR=true git rebase --continue && git push origin main`

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

## CSS quirk
- `.cal-modal.open` and the gallery lightbox use `pointer-events: all` (non-standard but intentional) — don't change to `auto`
