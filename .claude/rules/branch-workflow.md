# Branch & PR workflow

- **`develop` is the integration branch.** Every branch — bug fixes, features, iterations, doc updates — is cut from `develop` and opens a GitHub pull request **into `develop`**.
- **`main` is release-only.** It advances solely by merging `release/<timestamp>` branches (cut from `develop` by the `/release` skill), and each such merge is tagged `v<major>.<minor>.<patch>`. Never branch off `main`, never open a PR into `main` for feature work, and never commit to `main` directly. After a release merges, `main` is back-merged into `develop` so the two stay in lock-step.
- **GitHub is the remote** — use `gh`.
- Cut releases with the `/release` skill (commitizen; bump rules in `.cz.toml`). See `pull-requests.md` for PR titles.
