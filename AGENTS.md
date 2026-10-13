# Agent operating rules

## Always merge your own PRs

Do **not** wait for Wlad (or any human) to review, approve, or merge pull requests.

For work in this repository, cloud/coding agents must:

1. Create the PR as needed (draft is fine while iterating).
2. Finish implementation, tests, and deploy steps themselves.
3. **Merge into `main` themselves** before ending the turn — via `gh pr merge` (mark ready for review first if the PR is still a draft) or by merging the branch into `main` and pushing.
4. Close/complete the PR so it is not left open after the code is already on `main`.

Human review is optional and must never be a blocker for merge or deploy.
