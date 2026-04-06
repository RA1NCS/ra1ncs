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
CACHE_PATH = Path("cache/loc_cache.txt")

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


# load per-repo loc cache (skips re-fetching unchanged repos)
def load_cache():
    cache = {}
    if CACHE_PATH.exists():
        for line in CACHE_PATH.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split("\t")
            if len(parts) == 4:
                name, sha, a, d = parts
                cache[name] = (sha, int(a), int(d))
    return cache


def save_cache(cache):
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    lines = ["# repo<TAB>head_sha<TAB>additions<TAB>deletions"]
    for name, (sha, a, d) in sorted(cache.items()):
        lines.append(f"{name}\t{sha}\t{a}\t{d}")
    CACHE_PATH.write_text("\n".join(lines) + "\n")


# walk every commit on the default branch authored by user, sum add/del
def fetch_repo_loc(owner, name, user_id):
    add_total = 0
    del_total = 0
    cursor = None
    q = """
    query($owner: String!, $name: String!, $userId: ID!, $cursor: String) {
      repository(owner: $owner, name: $name) {
        defaultBranchRef {
          target {
            ... on Commit {
              history(author: {id: $userId}, first: 100, after: $cursor) {
                pageInfo { hasNextPage endCursor }
                nodes { additions deletions }
              }
            }
          }
        }
      }
    }
    """
    while True:
        d = gql(q, {"owner": owner, "name": name, "userId": user_id, "cursor": cursor})
        ref = d["repository"]["defaultBranchRef"]
        if not ref or not ref["target"]:
            return 0, 0
        hist = ref["target"]["history"]
        for n in hist["nodes"]:
            add_total += n["additions"]
            del_total += n["deletions"]
        if not hist["pageInfo"]["hasNextPage"]:
            break
        cursor = hist["pageInfo"]["endCursor"]
    return add_total, del_total


# pull repos, langs, contribs in one query then per-repo loc with caching
def fetch_stats():
    q = """
    query($login: String!) {
      user(login: $login) {
        id
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
            nameWithOwner
            stargazerCount
            languages(first: 10, orderBy: {field: SIZE, direction: DESC}) {
              edges { size node { name } }
            }
            defaultBranchRef { target { ... on Commit { oid } } }
          }
        }
      }
    }
    """
    d = gql(q, {"login": USER})["user"]
    user_id = d["id"]
    repos = d["repositories"]["nodes"]
    stars = sum(r["stargazerCount"] for r in repos)

    # aggregate language bytes across owned repos, skipping markup/config
    lang_bytes = {}
    for r in repos:
        for e in r["languages"]["edges"]:
            n = e["node"]["name"]
            if n.lower() in LANG_BLOCKLIST:
                continue
            lang_bytes[n] = lang_bytes.get(n, 0) + e["size"]
    total_bytes = sum(lang_bytes.values())
    top = sorted(lang_bytes.items(), key=lambda x: -x[1])[:3]
    top_langs = [(n, b / total_bytes * 100) for n, b in top] if total_bytes else []

    # per-repo loc with cache: skip if head sha unchanged
    cache = load_cache()
    new_cache = {}
    for r in repos:
        full = r["nameWithOwner"]
        ref = r["defaultBranchRef"]
        if not ref or not ref["target"]:
            continue
        head = ref["target"]["oid"]
        if full in cache and cache[full][0] == head:
            new_cache[full] = cache[full]
            continue
        owner, name = full.split("/", 1)
        a, dl = fetch_repo_loc(owner, name, user_id)
        new_cache[full] = (head, a, dl)
    save_cache(new_cache)

    add_total = sum(v[1] for v in new_cache.values())
    del_total = sum(v[2] for v in new_cache.values())
    net_loc = add_total - del_total

    return {
        "repos": d["repositories"]["totalCount"],
        "contributed": d["repositoriesContributedTo"]["totalCount"],
        "stars": stars,
        "followers": d["followers"]["totalCount"],
        "commits": d["contributionsCollection"]["totalCommitContributions"]
        + d["contributionsCollection"]["restrictedContributionsCount"],
        "loc_net": net_loc,
        "loc_add": add_total,
        "loc_del": del_total,
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
        "bg": "#0d1117",
        "border": "#30363d",
        "fg": "#c9d1d9",
        "label": "#cc6666",
        "value": "#79b8ff",
        "dim": "#6e7681",
        "accent": "#cc6666",
        "art": "#8b949e",
        "plus": "#7ee787",
        "minus": "#ff7b72",
    },
    "light": {
        "bg": "#ffffff",
        "border": "#d0d7de",
        "fg": "#1f2328",
        "label": "#cf222e",
        "value": "#0969da",
        "dim": "#8c959f",
        "accent": "#cf222e",
        "art": "#656d76",
        "plus": "#1a7f37",
        "minus": "#cf222e",
    },
}

PANEL_CHARS = 72

# markup / config / docs that aren't really programming languages
LANG_BLOCKLIST = {
    "html",
    "css",
    "scss",
    "sass",
    "less",
    "stylus",
    "vue",
    "svelte",
    "jupyter notebook",
    "tex",
    "markdown",
    "dockerfile",
    "makefile",
    "shell",
    "powershell",
    "batchfile",
    "yaml",
    "json",
    "xml",
    "toml",
    "roff",
    "groff",
    "vim script",
    "vim snippet",
    "git config",
    "ini",
    "procfile",
    "csv",
    "tsv",
}


def esc(s):
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


# build the right-side neofetch panel as a list of typed lines
def build_panel(s):
    L = []
    L.append(("header", "shreyan@ra1ncs"))
    L.append(("blank", None))
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
    L.append(("kv", "languages.stack", "context engineering, model adaptation, infra"))
    L.append(("blank", None))
    L.append(
        ("kv", "hobbies.software", "agentic systems, eval harnesses, rl post-training")
    )
    L.append(("kv", "hobbies.rig", "terminal ricing, dotfile golf, homelab tinkering"))
    L.append(("kv", "hobbies.markets", "options flow, vol surfaces, microstructure"))
    L.append(("blank", None))
    L.append(("section", "contact"))
    L.append(("kv", "email.dev", "gshreyan.dev@gmail.com"))
    L.append(("kv", "email.work", "gshreyan.work@gmail.com"))
    L.append(("kv", "instagram", "gshreyan_"))
    L.append(("kv", "discord", "demonlxrd"))
    L.append(("blank", None))
    L.append(("section", "github stats (live)"))
    L.append(
        (
            "kv2",
            "repos",
            f"{s['repos']} {{contributed: {s['contributed']}}}",
            "stars",
            str(s["stars"]),
        )
    )
    L.append(("kv2", "commits", str(s["commits"]), "followers", str(s["followers"])))
    L.append(("loc", "github loc", s["loc_net"], s["loc_add"], s["loc_del"]))
    return L


def render(stats, theme):
    p = THEMES[theme]
    font_size = 17
    char_w = 10.4
    line_h = 23
    pad_x = 22
    pad_y = 24

    art_w = max(len(l) for l in ART)
    art_h = len(ART)
    panel = build_panel(stats)
    panel_h = len(panel)

    rows = max(art_h, panel_h)
    total_h = int(rows * line_h + pad_y * 2)
    art_x = pad_x
    panel_x = int(pad_x + (art_w + 3) * char_w)
    total_w = int(panel_x + (PANEL_CHARS + 2) * char_w + pad_x)
    base_y = pad_y + font_size
    # vertically center the shorter block against the taller one
    art_y_offset = max(0, (rows - art_h) // 2) * line_h
    panel_y_offset = max(0, (rows - panel_h) // 2) * line_h

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" '
        f'viewBox="0 0 {total_w} {total_h}" font-family="\'JetBrainsMono Nerd Font\', \'JetBrains Mono\', ui-monospace, monospace" font-size="{font_size}">',
        '<defs><style>@import url("https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;600&amp;display=swap");</style></defs>',
        f'<rect x="0.5" y="0.5" width="{total_w-1}" height="{total_h-1}" rx="12" fill="{p["bg"]}" stroke="{p["border"]}"/>',
    ]

    # ascii art on the left
    for i, line in enumerate(ART):
        y = base_y + art_y_offset + i * line_h
        parts.append(
            f'<text x="{art_x}" y="{y}" fill="{p["art"]}" stroke="{p["art"]}" stroke-width="0.9" paint-order="stroke fill" font-family="Menlo, Monaco, Courier New, monospace" font-weight="900" xml:space="preserve">{esc(line)}</text>'
        )

    # build a dot-leader fill of exactly n characters using ". " pattern
    def dot_fill(n):
        if n <= 0:
            return ""
        # ". . . ." pattern: dot then space, repeated
        s = (". " * ((n // 2) + 1))[:n]
        return s

    # neofetch panel on the right
    for i, entry in enumerate(panel):
        y = base_y + panel_y_offset + i * line_h
        kind = entry[0]
        if kind == "header":
            txt = entry[1]
            trailing = max(0, PANEL_CHARS - len(txt) - 1)
            parts.append(
                f'<text x="{panel_x}" y="{y}" fill="{p["accent"]}" font-weight="600" xml:space="preserve">'
                f'{esc(txt)} <tspan fill="{p["dim"]}">{"─" * trailing}</tspan></text>'
            )
        elif kind == "section":
            label = entry[1]
            inner = f" {label} "
            side = max(2, (PANEL_CHARS - len(inner)) // 2)
            left = "─" * side
            right = "─" * (PANEL_CHARS - len(inner) - side)
            parts.append(
                f'<text x="{panel_x}" y="{y}" fill="{p["dim"]}" xml:space="preserve">'
                f'{left}<tspan fill="{p["accent"]}" font-weight="600">{esc(inner)}</tspan>{right}</text>'
            )
        elif kind == "kv":
            label, value = entry[1], entry[2]
            prefix = f". {label}: "
            suffix = f" {value}"
            gap = PANEL_CHARS - len(prefix) - len(suffix)
            fill = dot_fill(gap)
            parts.append(
                f'<text x="{panel_x}" y="{y}" xml:space="preserve">'
                f'<tspan fill="{p["dim"]}">. </tspan>'
                f'<tspan fill="{p["label"]}">{esc(label)}:</tspan>'
                f'<tspan fill="{p["dim"]}"> {esc(fill)} </tspan>'
                f'<tspan fill="{p["value"]}">{esc(value)}</tspan></text>'
            )
        elif kind == "kv2":
            label1, value1, label2, value2 = entry[1], entry[2], entry[3], entry[4]
            half = PANEL_CHARS // 2 - 1
            # left half
            prefix1 = f". {label1}: "
            suffix1 = f" {value1}"
            gap1 = half - len(prefix1) - len(suffix1)
            fill1 = dot_fill(gap1)
            # right half
            prefix2 = f"{label2}: "
            suffix2 = f" {value2}"
            gap2 = half - len(prefix2) - len(suffix2)
            fill2 = dot_fill(gap2)
            parts.append(
                f'<text x="{panel_x}" y="{y}" xml:space="preserve">'
                f'<tspan fill="{p["dim"]}">. </tspan>'
                f'<tspan fill="{p["label"]}">{esc(label1)}:</tspan>'
                f'<tspan fill="{p["dim"]}"> {esc(fill1)} </tspan>'
                f'<tspan fill="{p["value"]}">{esc(value1)}</tspan>'
                f'<tspan fill="{p["dim"]}"> | </tspan>'
                f'<tspan fill="{p["label"]}">{esc(label2)}:</tspan>'
                f'<tspan fill="{p["dim"]}"> {esc(fill2)} </tspan>'
                f'<tspan fill="{p["value"]}">{esc(value2)}</tspan></text>'
            )
        elif kind == "loc":
            label, net, add, dl = entry[1], entry[2], entry[3], entry[4]
            net_str = f"{net:,}"
            value_str = f"{net_str} ( +{fmt_num(add)}, -{fmt_num(dl)} )"
            prefix = f". {label}: "
            suffix = f" {value_str}"
            gap = PANEL_CHARS - len(prefix) - len(suffix)
            fill = dot_fill(gap)
            parts.append(
                f'<text x="{panel_x}" y="{y}" xml:space="preserve">'
                f'<tspan fill="{p["dim"]}">. </tspan>'
                f'<tspan fill="{p["label"]}">{esc(label)}:</tspan>'
                f'<tspan fill="{p["dim"]}"> {esc(fill)} </tspan>'
                f'<tspan fill="{p["value"]}">{net_str} ( </tspan>'
                f'<tspan fill="{p["plus"]}">+{fmt_num(add)}</tspan>'
                f'<tspan fill="{p["value"]}">, </tspan>'
                f'<tspan fill="{p["minus"]}">-{fmt_num(dl)}</tspan>'
                f'<tspan fill="{p["value"]}"> )</tspan></text>'
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
        "<picture>\n"
        f'  <source media="(prefers-color-scheme: dark)" srcset="dark_mode.svg?v={v}">\n'
        f'  <source media="(prefers-color-scheme: light)" srcset="light_mode.svg?v={v}">\n'
        f'  <img alt="shreyan@ra1ncs" src="dark_mode.svg?v={v}">\n'
        "</picture>\n"
    )
    Path("README.md").write_text(readme)
    print("ok:", s)


if __name__ == "__main__":
    main()
