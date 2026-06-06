# Release PR Description Template

Use this template when creating the release PR (fill in `{version}`):

```markdown
## Release v{version}

This PR promotes `develop` to `main` for release **v{version}**. It contains:
- Version bump to {version} (`.cz.toml`, `pyproject.toml`, the README `Version` badge, `uv.lock`)
- Updated `CHANGELOG.md` (the new version's section plus full history)

**Merge with a merge commit (do not squash)** so the tagged bump commit is preserved on `main`.

### Post-merge actions
After this PR is merged, the `/release` skill:
1. Pushes the `v{version}` tag to `main`.
2. Creates the GitHub Release `v{version}` with `gh release create`, using the new version's `CHANGELOG.md` section as the description.

The skill then back-merges `main` into `develop` to keep them in lock-step.
```
