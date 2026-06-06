# Changelog Format

Write changelog entries to `CHANGELOG.md` using this format:

```markdown
## {version} ({release_date})

### 🚀 Features

#### {short_desc}
{your user-friendly description here}

*[#{number}]({url}) by @{author}*

### 🐛 Bug Fixes
...

### ♻️ Refactoring
...
```

## Section Order

Only include sections that have PRs:

1. 🚀 Features
2. 🐛 Bug Fixes
3. ♻️ Refactoring
4. 📚 Documentation
5. 🧪 Tests
6. 🔧 CI/Build
7. 📦 Other Changes

## Writing Guidelines

For each PR, write a **user-friendly description** that:

- Focuses on **value and impact** for end users, not technical implementation
- Is understandable by someone who uses the app but isn't a developer
- Is 1-2 sentences maximum

### By Change Type

| Type | Focus on... | Example |
|------|-------------|---------|
| Features | What users can now DO | "You can now filter prompts by visibility status directly from the sidebar." |
| Fixes | What problem was SOLVED | "Fixed an issue where group members couldn't see shared prompts." |
| Refactors | Brief note, mention no user-visible changes | "Internal code improvements for better maintainability. No user-visible changes." |

## Important

After the new version section, preserve all existing changelog content (previous versions).
