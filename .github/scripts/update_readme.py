#!/usr/bin/env python3
"""
Auto-updates the Featured Projects section of the profile README.

Logic:
  1. Fetch pinned repos via GraphQL (user controls what is featured by pinning).
  2. If none pinned, fall back to top non-fork public repos sorted by
     (stars DESC, pushed_at DESC), excluding the profile repo itself.
  3. Show up to 4 repos, laid out in a responsive 2-column table.
  4. Replace content between <!-- PROJECTS_START --> and <!-- PROJECTS_END -->.
"""

import os
import re
import sys
import json
import requests
from datetime import datetime, timezone

USERNAME = "su6osec"
TOKEN    = os.environ["GITHUB_TOKEN"]
MAX_SHOW = 4

HEADERS = {
    "Authorization": f"Bearer {TOKEN}",
    "Accept": "application/vnd.github+json",
    "X-GitHub-Api-Version": "2022-11-28",
}

# Language → shield colour (hex without #)
LANG_COLOURS = {
    "Go":         "00ADD8",
    "Python":     "3776AB",
    "TypeScript": "3178C6",
    "JavaScript": "F7DF1E",
    "Rust":       "CE422B",
    "C":          "555555",
    "C++":        "F34B7D",
    "Shell":      "4EAA25",
    "Kotlin":     "7F52FF",
    "Java":       "B07219",
}
LANG_LOGO = {
    "Go":         "go&logoColor=white",
    "Python":     "python&logoColor=white",
    "TypeScript": "typescript&logoColor=white",
    "JavaScript": "javascript&logoColor=black",
    "Rust":       "rust&logoColor=white",
    "Shell":      "gnubash&logoColor=white",
    "Kotlin":     "kotlin&logoColor=white",
    "Java":       "java&logoColor=white",
}


# ── API helpers ──────────────────────────────────────────────────────────────

def graphql(query: str) -> dict:
    resp = requests.post(
        "https://api.github.com/graphql",
        json={"query": query},
        headers={**HEADERS, "Content-Type": "application/json"},
        timeout=20,
    )
    resp.raise_for_status()
    return resp.json()


def get_pinned_repos() -> list[dict]:
    q = """
    {
      user(login: "%s") {
        pinnedItems(first: 6, types: REPOSITORY) {
          nodes {
            ... on Repository {
              name
              description
              stargazerCount
              forkCount
              primaryLanguage { name color }
              repositoryTopics(first: 5) { nodes { topic { name } } }
              url
              homepageUrl
              updatedAt
              isArchived
            }
          }
        }
      }
    }
    """ % USERNAME
    data = graphql(q)
    return data["data"]["user"]["pinnedItems"]["nodes"]


def get_top_repos() -> list[dict]:
    resp = requests.get(
        f"https://api.github.com/users/{USERNAME}/repos"
        f"?sort=pushed&per_page=50&type=public",
        headers=HEADERS,
        timeout=20,
    )
    resp.raise_for_status()
    repos = [
        r for r in resp.json()
        if not r["fork"] and r["name"] != USERNAME
    ]
    # Sort: stars DESC, then pushed DESC
    repos.sort(key=lambda r: (-r["stargazers_count"], r["pushed_at"]), reverse=False)
    return repos[:MAX_SHOW]


def file_exists(repo: str, path: str) -> bool:
    resp = requests.get(
        f"https://api.github.com/repos/{USERNAME}/{repo}/contents/{path}",
        headers=HEADERS,
        timeout=10,
    )
    return resp.status_code == 200


def install_snippet(repo: str, lang: str | None) -> str:
    """Return a short install/quickstart code block for the repo."""
    if lang == "Go" and file_exists(repo, "go.mod"):
        return f"```bash\ngo install github.com/{USERNAME}/{repo}@latest\n```"
    if file_exists(repo, "package.json"):
        return f"```bash\nnpm install  # see repo for details\n```"
    if file_exists(repo, "requirements.txt") or file_exists(repo, "setup.py"):
        return f"```bash\npip install -r requirements.txt\n```"
    return (
        f"```bash\ngit clone https://github.com/{USERNAME}/{repo}\n```"
    )


# ── Markdown generation ──────────────────────────────────────────────────────

def lang_badge(lang: str | None) -> str:
    if not lang:
        return ""
    colour = LANG_COLOURS.get(lang, "555555")
    logo   = LANG_LOGO.get(lang, lang.lower())
    return (
        f"![{lang}](https://img.shields.io/badge/{lang.replace(' ', '%20')}"
        f"-{colour}?style=flat-square&logo={logo})"
    )


def repo_card(repo: dict, is_graphql: bool = False) -> str:
    """Render a single repo card (one table cell)."""
    name  = repo["name"] if is_graphql else repo["name"]
    url   = repo.get("url") or f"https://github.com/{USERNAME}/{name}"
    desc  = (repo.get("description") or "").strip() or "_No description yet._"

    if is_graphql:
        lang  = (repo.get("primaryLanguage") or {}).get("name")
        stars = repo.get("stargazerCount", 0)
        topics = [
            n["topic"]["name"]
            for n in (repo.get("repositoryTopics") or {}).get("nodes", [])
        ]
    else:
        lang  = repo.get("language")
        stars = repo.get("stargazers_count", 0)
        topics = repo.get("topics", [])

    updated_raw = repo.get("updatedAt") or repo.get("updated_at") or ""
    try:
        updated = datetime.fromisoformat(
            updated_raw.replace("Z", "+00:00")
        ).strftime("%b %Y")
    except Exception:
        updated = ""

    topic_badges = " ".join(
        f"`{t}`" for t in topics[:4]
    )

    stars_badge = (
        f"![Stars](https://img.shields.io/github/stars/{USERNAME}/{name}"
        f"?style=flat-square&color=6366f1)"
    )
    license_badge = (
        f"![License](https://img.shields.io/github/license/{USERNAME}/{name}"
        f"?style=flat-square&color=6366f1)"
    )

    snippet = install_snippet(name, lang)

    lines = [
        f"### [{name}]({url})",
        desc,
        "",
        " ".join(filter(None, [lang_badge(lang), stars_badge, license_badge])),
    ]
    if topic_badges:
        lines.append("")
        lines.append(topic_badges)
    lines += ["", snippet]
    if updated:
        lines += ["", f"<sub>Updated {updated}</sub>"]

    return "\n".join(lines)


def build_projects_section(repos: list[dict], is_graphql: bool) -> str:
    if not repos:
        return "_No public projects yet — check back soon!_\n"

    if len(repos) == 1:
        return repo_card(repos[0], is_graphql) + "\n"

    # 2-column table layout
    rows = []
    for i in range(0, len(repos), 2):
        left  = repo_card(repos[i], is_graphql)
        right = repo_card(repos[i + 1], is_graphql) if i + 1 < len(repos) else ""
        right_cell = f"\n{right}\n" if right else ""
        rows.append(
            f"<tr>\n"
            f"<td width=\"50%\" valign=\"top\">\n\n{left}\n\n</td>\n"
            f"<td width=\"50%\" valign=\"top\">{right_cell}</td>\n"
            f"</tr>"
        )

    table = "<table>\n" + "\n".join(rows) + "\n</table>"
    return table + "\n"


# ── README patcher ───────────────────────────────────────────────────────────

START_MARKER = "<!-- PROJECTS_START -->"
END_MARKER   = "<!-- PROJECTS_END -->"
AUTO_NOTE    = "<!-- auto-generated by update-readme.yml · do not edit manually -->"


def patch_readme(original: str, new_section: str) -> str:
    pattern = re.compile(
        re.escape(START_MARKER) + r".*?" + re.escape(END_MARKER),
        re.DOTALL,
    )
    replacement = (
        f"{START_MARKER}\n{AUTO_NOTE}\n\n"
        f"{new_section}\n"
        f"{END_MARKER}"
    )
    if not pattern.search(original):
        print("ERROR: markers not found in README.md", file=sys.stderr)
        sys.exit(1)
    return pattern.sub(replacement, original)


# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    # 1. Try pinned repos first
    pinned = get_pinned_repos()
    pinned = [r for r in pinned if not r.get("isArchived")]
    is_gql = True

    if pinned:
        repos      = pinned[:MAX_SHOW]
        source_msg = f"pinned ({len(repos)} repo(s))"
    else:
        repos      = get_top_repos()
        is_gql     = False
        source_msg = f"top non-fork repos ({len(repos)} repo(s))"

    print(f"Source: {source_msg}")
    for r in repos:
        print(" ·", r["name"])

    section = build_projects_section(repos, is_gql)

    with open("README.md", "r", encoding="utf-8") as fh:
        original = fh.read()

    patched = patch_readme(original, section)

    if patched == original:
        print("README.md unchanged — nothing to commit.")
        return

    with open("README.md", "w", encoding="utf-8") as fh:
        fh.write(patched)

    print("README.md updated.")


if __name__ == "__main__":
    main()
