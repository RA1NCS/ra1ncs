#!/usr/bin/env python3
# generates dark_mode.svg + light_mode.svg with live github stats
# run via .github/workflows/update.yml on a cron

import os
import datetime
from pathlib import Path
import requests

USER = os.environ.get("USER_NAME", "ra1ncs")
TOKEN = os.environ["ACCESS_TOKEN"]
BIRTH = datetime.date(2004, 10, 8)
SHIPPING = "<stealth startup>"

ART = Path("art.txt").read_text().rstrip("\n").splitlines()

GQL_URL = "https://api.github.com/graphql"
HEADERS = {"Authorization": f"bearer {TOKEN}"}

# minimal graphql wrapper
def gql(query, variables=None):
    r = requests.post(
        GQL_URL,
        json={"query": query, "variables": variables or {}},
        headers=HEADERS,
        timeout=30,
    )
    r.raise_for_status()
    data = r.json()
    if "errors" in data:
        raise RuntimeError(data["errors"])
    return data["data"]

# years/months/days since birth
def uptime_str():
    today = datetime.date.today()
    y = today.year - BIRTH.year
    m = today.month - BIRTH.month
    d = today.day - BIRTH.day
    if d < 0:
        m -= 1
        prev = today.replace(day=1) - datetime.timedelta(days=1)
        d += prev.day
    if m < 0:
        y -= 1
        m += 12
    return f"{y} years, {m} months, {d} days"

# pull repos, langs, contribs in one query
def fetch_stats():
    q = """
    query($login: String!) {
      user(login: $login) {
        followers { totalCount }
        repositoriesContributedTo(first: 1, contributionTypes: [COMMIT, PULL_REQUEST, ISSUE, REPOSITORY]) {
          totalCount
        }
        contributionsCollection {
          totalCommitContributions
          restrictedContributionsCount
        }
        repositories(first: 100, ownerAffiliations: OWNER, isFork: false, orderBy: {field: UPDATED_AT, direction: DESC}) {
          totalCount
          nodes {
            stargazerCount
            languages(first: 10, orderBy: {field: SIZE, direction: DESC}) {
              edges { size node { name } }
            }
          }
        }
      }
    }
    """
    d = gql(q, {"login": USER})["user"]
    repos = d["repositories"]["nodes"]
    stars = sum(r["stargazerCount"] for r in repos)

    # aggregate language bytes across owned repos
    lang_bytes = {}
    for r in repos:
        for e in r["languages"]["edges"]:
            n = e["node"]["name"]
            lang_bytes[n] = lang_bytes.get(n, 0) + e["size"]
    total_bytes = sum(lang_bytes.values())
    top = sorted(lang_bytes.items(), key=lambda x: -x[1])[:3]
    top_langs = [(n, b / total_bytes * 100) for n, b in top] if total_bytes else []

    # rough loc estimate from total bytes (~40 chars/line)
    loc = total_bytes // 40

    return {
        "repos": d["repositories"]["totalCount"],
        "contributed": d["repositoriesContributedTo"]["totalCount"],
        "stars": stars,
        "followers": d["followers"]["totalCount"],
        "commits": d["contributionsCollection"]["totalCommitContributions"]
                 + d["contributionsCollection"]["restrictedContributionsCount"],
        "loc": loc,
        "top_langs": top_langs,
    }

def fmt_num(n):
    if n >= 1_000_000:
        return f"{n/1_000_000:.2f}M"
    if n >= 1_000:
        return f"{n/1_000:.1f}K"
    return str(n)

THEMES = {
    "dark": {
        "bg": "#0d1117", "border": "#30363d",
        "fg": "#c9d1d9", "label": "#cc6666", "value": "#79b8ff",
        "dim": "#6e7681", "accent": "#7ee787", "art": "#8b949e",
    },
    "light": {
        "bg": "#ffffff", "border": "#d0d7de",
        "fg": "#1f2328", "label": "#cf222e", "value": "#0969da",
        "dim": "#8c959f", "accent": "#1a7f37", "art": "#656d76",
    },
}

def esc(s):
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

# build the right-side neofetch panel as a list of typed lines
def build_panel(s):
    L = []
    L.append(("header", "shreyan@ra1ncs"))
    L.append(("rule", None))
    L.append(("kv", "currently.shipping", SHIPPING.lower()))
    L.append(("blank", None))
    L.append(("kv", "identity.role", "student @ drexel university (cs)"))
    L.append(("kv", "identity.uptime", uptime_str()))
    L.append(("kv", "setup.daily", "macbook pro · m3 pro"))
    L.append(("kv", "setup.heavy", "ryzen 6900hs + rtx 3070 ti"))
    L.append(("kv", "tools.ide", "cursor / glass (zed) / subspace"))
    L.append(("kv", "tools.shell", "ghostty + tmux + zsh"))
    L.append(("blank", None))
    L.append(("kv", "languages.programming", "python, typescript, rust, c++"))
    if s["top_langs"]:
        top_str = ", ".join(f"{n.lower()} {p:.0f}%" for n, p in s["top_langs"])
        L.append(("kv", "languages.top", top_str))
    L.append(("kv", "languages.stack", "context engineering, model adaptation, inference infra"))
    L.append(("blank", None))
    L.append(("kv", "hobbies.software", "agentic systems, eval harnesses, rl post-training"))
    L.append(("kv", "hobbies.tinker", "terminal ricing, dotfile golf, homelab tinkering"))
    L.append(("kv", "hobbies.markets", "day trading the open, options flow, microstructure"))
    L.append(("blank", None))
    L.append(("section", "contact"))
    L.append(("kv", "email.dev", "gshreyan.dev@gmail.com"))
    L.append(("kv", "email.work", "gshreyan.work@gmail.com"))
    L.append(("kv", "instagram", "gshreyan_"))
    L.append(("kv", "discord", "demonlxrd"))
    L.append(("blank", None))
    L.append(("section", "github stats"))
    L.append(("kv", "repos", f"{s['repos']} {{contributed: {s['contributed']}}}"))
    L.append(("kv", "stars", str(s['stars'])))
    L.append(("kv", "followers", str(s['followers'])))
    L.append(("kv", "commits", str(s['commits'])))
    L.append(("kv", "github loc", f"~{fmt_num(s['loc'])}"))
    return L

def render(stats, theme):
    p = THEMES[theme]
    char_w = 8.4
    line_h = 18
    pad_x = 28
    pad_y = 26

    art_w = max(len(l) for l in ART)
    art_h = len(ART)
    panel = build_panel(stats)
    panel_h = len(panel)

    rows = max(art_h, panel_h)
    total_h = int(rows * line_h + pad_y * 2)
    art_x = pad_x
    panel_x = int(pad_x + (art_w + 4) * char_w)
    total_w = int(panel_x + 70 * char_w + pad_x)
    base_y = pad_y + 14

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{total_w}" height="{total_h}" '
        f'viewBox="0 0 {total_w} {total_h}" font-family="\'JetBrainsMono Nerd Font\', \'JetBrains Mono\', ui-monospace, monospace" font-size="13">',
        '<defs><style>@import url("https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;600&amp;display=swap");</style></defs>',
        f'<rect x="0.5" y="0.5" width="{total_w-1}" height="{total_h-1}" rx="12" fill="{p["bg"]}" stroke="{p["border"]}"/>',
    ]

    # ascii art on the left
    for i, line in enumerate(ART):
        y = base_y + i * line_h
        parts.append(
            f'<text x="{art_x}" y="{y}" fill="{p["art"]}" font-family="Menlo, Monaco, Courier New, monospace" font-weight="900" xml:space="preserve">{esc(line)}</text>'
        )

    # neofetch panel on the right
    for i, entry in enumerate(panel):
        y = base_y + i * line_h
        kind = entry[0]
        if kind == "header":
            parts.append(
                f'<text x="{panel_x}" y="{y}" fill="{p["accent"]}" font-weight="600">{esc(entry[1])}</text>'
            )
        elif kind == "rule":
            parts.append(
                f'<line x1="{panel_x}" y1="{y-4}" x2="{total_w - pad_x}" y2="{y-4}" stroke="{p["dim"]}" stroke-width="1"/>'
            )
        elif kind == "section":
            label = entry[1]
            parts.append(
                f'<text x="{panel_x}" y="{y}" fill="{p["accent"]}" font-weight="600">─ {esc(label)} ─</text>'
            )
        elif kind == "kv":
            label, value = entry[1], entry[2]
            parts.append(
                f'<text x="{panel_x}" y="{y}" xml:space="preserve">'
                f'<tspan fill="{p["dim"]}">. </tspan>'
                f'<tspan fill="{p["label"]}">{esc(label)}:</tspan>'
                f'<tspan fill="{p["value"]}"> {esc(value)}</tspan></text>'
            )

    parts.append("</svg>")
    return "\n".join(parts)

def main():
    s = fetch_stats()
    Path("dark_mode.svg").write_text(render(s, "dark"))
    Path("light_mode.svg").write_text(render(s, "light"))
    # bust github camo cache by stamping a unique query param into the readme
    v = int(datetime.datetime.utcnow().timestamp())
    readme = (
        '<picture>\n'
        f'  <source media="(prefers-color-scheme: dark)" srcset="dark_mode.svg?v={v}">\n'
        f'  <source media="(prefers-color-scheme: light)" srcset="light_mode.svg?v={v}">\n'
        f'  <img alt="shreyan@ra1ncs" src="dark_mode.svg?v={v}">\n'
        '</picture>\n'
    )
    Path("README.md").write_text(readme)
    print("ok:", s)

if __name__ == "__main__":
    main()
