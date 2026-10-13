# Agent operating rules

## Always merge and deploy yourselves

Do **not** wait for Wlad (or any human) to review, approve, merge, enable hosting, or click dashboard toggles.

For work in this repository, cloud/coding agents must:

1. Create the PR as needed (draft is fine while iterating).
2. Finish implementation, tests, and deploy steps themselves.
3. **Merge into `main` themselves** before ending the turn — via `gh pr merge` (mark ready for review first if the PR is still a draft) or by merging the branch into `main` and pushing.
4. Close/complete the PR so it is not left open after the code is already on `main`.
5. **Finish hosting yourselves.** Do **not** ask Wlad to open Settings → Pages or any other dashboard toggle. Prefer publish methods agents can complete with repo write access (e.g. force-update the `gh-pages` branch + jsDelivr CDN URL). If GitHub Pages site-enable APIs return 403 to the integration token, switch hosting approach — never block on a human click.

Human review / manual dashboard clicks are optional and must never be a blocker for merge or deploy.
