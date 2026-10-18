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

Before merging or deploying any change that touches Listening Log layout, filters, chrome, pickers, charts, or CSS/HTML/JS under `pocketcasts-history/` or `docs/`, agents **must** verify the live UI on a phone-width viewport and confirm **no content is clipped on the left or right**.

### Required checks (block ship if any fail)

Run the explorer at **≤430 CSS px** wide (also spot-check **390** and **320**). With a **long show title** selected (e.g. RapaduraCast / Ghibliotheque):

1. **Chrome bar:** brand, Eps/Hours, theme toggle, and Refresh are fully visible — nothing cut by the screen edge.
2. **Filter row:** Show field truncates with ellipsis *inside* its control; the Filters button is fully visible with clear right inset.
3. **Shows / combo picker:** Cancel, title, Done, search field, and list text all have horizontal inset; no letter clipped (`ancel` / `Don` / flush list text = fail).
4. **Page shell:** `document.documentElement.scrollWidth <= window.innerWidth` (no horizontal page scroll). Fixed overlays (picker, sheets, tab bar) stay inside the visual viewport.

### Known failure modes to re-test after CSS/flex changes

- iOS Safari: `input[type=search]` / combo inputs ignore `min-width: 0` for flex min-content — long values push Filters off-screen unless the Show flex item is forced to shrink (`flex: 1 1 0; width: 0; overflow: hidden`) and inputs are capped at `max-width: 100%`.
- `position: fixed` pickers at `left: 0; right: 0` ignore body safe-area padding and misalign when `visualViewport.offsetLeft` ≠ 0 — pin with `--vv-left` / `--vv-width` and pad with `max(…, var(--safe-left/right))`.
- `overflow-x: clip` alone is not enough on older iOS — keep `overflow-x: hidden` as a fallback on `html`/`body` and contain chrome / period-dock overflow.

### How to prove it

Prefer a real device or Puppeteer/Chrome at mobile viewport widths. Save at least one screenshot of (a) the filter row with a long show name and (b) the open Shows picker. **Do not merge/deploy if either shows edge clipping.** If a layout change cannot pass these checks, fix it in the same PR before shipping.
