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
