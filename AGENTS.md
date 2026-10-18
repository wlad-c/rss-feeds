# Agent operating rules

## Never wait for human PR review before merge or publish

Do **not** wait for Wlad (or any human) to review, approve, comment on, or merge a pull request before shipping. Do **not** leave work blocked on “please review / approve / merge this PR.”

Human review is optional after the fact. It must **never** be a gate for:

- merging to `main`
- publishing / deploying (including GitHub Pages or other hosting)
- enabling hosting or flipping dashboard toggles (agents must finish those themselves)

## Always merge and deploy yourselves

For work in this repository, cloud/coding agents must:

1. Create the PR as needed (draft is fine while iterating).
2. Finish implementation, tests, and deploy steps themselves.
3. **Merge into `main` themselves** before ending the turn — via `gh pr merge` (mark ready for review first if the PR is still a draft) or by merging the branch into `main` and pushing. Do this even if no human has reviewed the PR.
4. Close/complete the PR so it is not left open after the code is already on `main`.
5. **Finish hosting yourselves.** Do **not** ask Wlad to open Settings → Pages or any other dashboard toggle. Prefer publish methods agents can complete with repo write access (e.g. force-update the `gh-pages` branch + jsDelivr CDN URL). If GitHub Pages site-enable APIs return 403 to the integration token, switch hosting approach — never block on a human click.

If CI is still running, wait for required checks when feasible, then merge. Do **not** wait on human review, approval, or a merge click.

## Golden rule: never ship Listening Log UI with edge cutoffs

This has recurred across multiple fixes. Treat it as a **hard ship gate**, not a nice-to-have.

Before merging or deploying any change that touches Listening Log layout, filters, chrome, pickers, charts, or CSS/HTML/JS under `pocketcasts-history/` or `docs/`, agents **must**:

1. Keep the **padding-inset architecture** (do not regress it).
2. Run the automated edge check and fix until it passes.
3. Confirm screenshots still look inset on phone widths.

### Architecture (do not break)

Horizontal inset is owned by CSS tokens, not one-off margins:

- `--page-inline` (min 16px) + `--safe-left/right` → `--inset-left` / `--inset-right`
- `.wrap` gutters are **`border-left/right: max(16px, env(safe-area-inset-*)) solid transparent`** + `overflow-x: hidden` + `box-sizing: border-box`. **Never use padding for the page gutter** — overflowing flex children paint into padding and still reach the screen edge (`overflow` clips at the padding edge, not outside it).
- Elements that also use `.wrap` (`.chrome-inner`, `.period-bar`) must not reset those transparent borders (no `border: 0` / `border: 0.5px solid …` shorthand that wipes the gutter).
- Show field on mobile: `flex: 1 1 0; width: 0; overflow: hidden` so iOS search inputs cannot expand the row past Filters.
- **All focused text fields must be ≥16px** (`input.combo-picker-input`, `.combo-input`, filter-sheet search). Smaller fields trigger iOS focus-zoom; after typing in the Shows/Theme dropdown the visual viewport stays shifted and chrome/Filters look cut off on the sides.
- Fixed UI (tab bar, filter sheet, combo picker chrome) must use the same `--inset-*` tokens
- Never combine `left` + `right` + `width: 100%` / `max-width: 100%` on fixed elements (over-constrains and clips Cancel/Done)
- Body does **not** carry horizontal safe padding (fixed layers ignore it)

### Required automated checks (block ship if either fails)

Serve the UI, then run **both** gates:

```bash
cd docs && python3 -m http.server 8765
# other terminal:
node pocketcasts-history/scripts/check_mobile_edges.mjs http://127.0.0.1:8765
node pocketcasts-history/scripts/check_filter_combos.mjs http://127.0.0.1:8765
```

1. **`check_mobile_edges.mjs`** — chrome tools, Filters, filter sheet, and Shows picker must not spill past the viewport at **430 / 390 / 320** CSS px (including a long show title). Also requires picker search font-size ≥16px.
2. **`check_filter_combos.mjs`** — on **desktop/iPad widths (1180 / 1024 / 900 / 861)** Show, Country, and Theme comboboxes must open a **portaled, usable list** (height ≥100px, many visible options, not a 1–2 row clipped strip). Type-to-filter must keep a usable list. On **compact widths (430 / 390)** Show must open the full-screen picker with ≥16px search text.

Sticky filter chrome uses `overflow-x: hidden` for edge containment; that **clips** absolutely positioned dropdowns. Desktop combo lists must be portaled to `document.body` with `position: fixed` (see `.combo-list.is-ported`). **Do not merge/deploy on failure.**

### Manual spot checks

With a long show title selected:

1. Chrome: brand, Eps/Hours, theme, Refresh fully visible with clear side inset
2. Filter row: Show truncates inside its control; Filters fully visible
3. Shows picker + Filters sheet: Cancel/Clear/Done fully visible (not `ancel` / `Don`)
4. `document.documentElement.scrollWidth <= window.innerWidth`
5. **Desktop / iPad landscape (≥861px):** clicking Show, Country, and Theme opens a full-width dropdown with a scrollable option list (not Paste/AutoFill alone, not a tiny blue stub). Typing filters the list; choosing an option applies it.

### Deploy note

GitHub Pages serves **`main:/docs`** (this is what users should open). Also force-update **`gh-pages/pocketcasts-history/`** from `docs/`, bump `?v=` **and** the footer `build-stamp`, and purge jsDelivr `index.html` + CSS/JS. **Verify** `cdn.jsdelivr.net/.../index.html` actually shows the new `?v=` — branch CDN can keep serving old HTML for hours; tell users to use **github.io** if edges still clip. Never diagnose layout bugs from a stale CDN tab.
