#!/usr/bin/env python3
"""Fetch merged PRs since the last release tag and prepare data for changelog generation."""

import json
import re
import subprocess
import sys
from datetime import datetime

session_id = sys.argv[1] if len(sys.argv) > 1 else "default"

# Get version
version_result = subprocess.run(["cz", "version", "--project"], capture_output=True, text=True)
new_version = version_result.stdout.strip()
release_date = datetime.now().strftime("%Y-%m-%d")

# Get last tag date from main
tag_result = subprocess.run(
    ["git", "describe", "--tags", "--abbrev=0", "origin/main"],
    capture_output=True,
    text=True,
)
last_tag = tag_result.stdout.strip() if tag_result.returncode == 0 else None

last_tag_date = None
if last_tag:
    tag_date_result = subprocess.run(["git", "log", "-1", "--format=%aI", last_tag], capture_output=True, text=True)
    last_tag_date = datetime.fromisoformat(tag_date_result.stdout.strip())

# Get all merged PRs targeting develop
result = subprocess.run(
    [
        "gh",
        "pr",
        "list",
        "--state",
        "merged",
        "--base",
        "develop",
        "--limit",
        "100",
        "--json",
        "number,title,body,url,author,mergedAt",
    ],
    capture_output=True,
    text=True,
)
prs = json.loads(result.stdout)

# Filter PRs merged after the last tag
filtered_prs = []
for pr in prs:
    merged_at = pr.get("mergedAt")
    if merged_at:
        pr_date = datetime.fromisoformat(merged_at)
        if last_tag_date is None or pr_date > last_tag_date:
            filtered_prs.append(pr)


# Parse conventional commit title
def parse_title(title):
    match = re.match(r"^(\w+)(?:\(([^)]+)\))?:\s*(.*)$", title)
    if match:
        return {
            "type": match.group(1),
            "scope": match.group(2) or "",
            "desc": match.group(3),
        }
    return {"type": "other", "scope": "", "desc": title}


TYPE_MAP = {
    "feat": "Features",
    "fix": "Bug Fixes",
    "refactor": "Refactoring",
    "docs": "Documentation",
    "test": "Tests",
    "ci": "CI/Build",
    "build": "CI/Build",
}

# Prepare PR data for Claude to process
pr_data = []
for pr in filtered_prs:
    parsed = parse_title(pr["title"])
    pr_data.append(
        {
            "number": pr["number"],
            "title": pr["title"],
            "description": pr.get("body", ""),
            "url": pr["url"],
            "author": pr["author"]["login"],
            "type": parsed["type"],
            "type_label": TYPE_MAP.get(parsed["type"], "Other Changes"),
            "short_desc": parsed["desc"],
        }
    )

# Save to temp file for Claude to read
output = {
    "version": new_version,
    "release_date": release_date,
    "prs": pr_data,
}

with open(f"/tmp/release_pr_data_{session_id}.json", "w") as f:
    json.dump(output, f, indent=2)

print(f"Prepared {len(pr_data)} PRs for changelog generation")
print(f"Data saved to /tmp/release_pr_data_{session_id}.json")
