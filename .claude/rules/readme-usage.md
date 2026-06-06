# README usage documentation

All CLI subcommands and options must be documented in `README.md` under the `## Usage` section.

When you add or change a subcommand or option in the `cli` package, update the `## Usage` section in the **same change**, so the documentation never drifts from the actual CLI. The `mdformat` pre-commit hook owns the README table of contents — don't hand-edit it.
