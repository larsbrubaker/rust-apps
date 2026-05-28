#!/usr/bin/env python3
"""Generate an HTML dashboard of GitHub stats for rust-apps and its submodules.

Discovers the parent repo from `git remote get-url origin` and the submodules
from `.gitmodules`, then queries the GitHub GraphQL API via the `gh` CLI for
stars, forks, watchers, open issues, and open PRs. Writes a self-contained
HTML file (no external assets) next to this script.

Usage:
    python repo_stats.py              # writes repo_stats.html
    python repo_stats.py --out X.html # writes to a custom path
    python repo_stats.py --json       # also emit repo_stats.json
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote


REPO_ROOT = Path(__file__).resolve().parent

# Hosts/paths that indicate a shields-style badge, not a real hero image.
BADGE_PATTERNS = [
    re.compile(p, re.I) for p in (
        r"img\.shields\.io",
        r"badge\.fury\.io",
        r"docs\.rs/[^/]+/badge",
        r"github\.com/[^/]+/[^/]+/actions/workflows/[^/]+/badge\.svg",
        r"github\.com/[^/]+/[^/]+/workflows/[^/]+/badge\.svg",
        r"codecov\.io",
        r"buymeacoffee\.com",
        r"opencollective\.com",
        r"/badge\.svg(?:$|\?)",
    )
]

# Match either ![alt](url ...) or <img ... src="url" ...>; first capturing group
# holds the markdown URL, second holds the HTML URL. Position-ordered.
_IMG_RE = re.compile(
    r'!\[[^\]]*\]\((?P<md>[^)\s]+)(?:\s+"[^"]*")?\s*\)|<img\b[^>]*\bsrc=["\'](?P<html>[^"\']+)["\']',
    re.I,
)
_README_NAMES = ("README.md", "Readme.md", "readme.md", "README.MD")

# A top-level hero image (any case, common extensions) is preferred over the
# first-image-in-README heuristic.
_HERO_FILE_RE = re.compile(r"^readme[_\-]?hero\.(png|jpe?g|gif|webp|svg)$", re.I)


def run(args: list[str], cwd: Path | None = None) -> str:
    result = subprocess.run(
        args, cwd=cwd, capture_output=True, text=True, encoding="utf-8",
    )
    if result.returncode != 0:
        sys.stderr.write(
            f"Command failed: {' '.join(args)}\n"
            f"  stdout: {result.stdout}\n  stderr: {result.stderr}\n"
        )
        raise SystemExit(result.returncode)
    return result.stdout


def parse_github_url(url: str) -> tuple[str, str] | None:
    """Extract (owner, name) from any common GitHub remote URL form."""
    pattern = r"(?:https?://github\.com/|git@github\.com:)([^/]+)/([^/]+?)(?:\.git)?/?$"
    m = re.match(pattern, url.strip())
    if not m:
        return None
    return m.group(1), m.group(2)


def discover_repos(root: Path) -> list[dict]:
    """Return [{label, owner, name}] for the parent repo plus each submodule."""
    repos: list[dict] = []
    seen: set[tuple[str, str]] = set()

    origin = run(["git", "-C", str(root), "remote", "get-url", "origin"]).strip()
    parent = parse_github_url(origin)
    if parent:
        owner, name = parent
        repos.append({"label": name, "owner": owner, "name": name, "is_parent": True})
        seen.add((owner.lower(), name.lower()))

    gitmodules = root / ".gitmodules"
    if gitmodules.exists():
        text = gitmodules.read_text(encoding="utf-8")
        section_re = re.compile(r'\[submodule\s+"([^"]+)"\](.*?)(?=\n\[|\Z)', re.S)
        for m in section_re.finditer(text):
            section = m.group(2)
            path_m = re.search(r"^\s*path\s*=\s*(.+)$", section, re.M)
            url_m = re.search(r"^\s*url\s*=\s*(.+)$", section, re.M)
            if not url_m:
                continue
            parsed = parse_github_url(url_m.group(1))
            if not parsed:
                continue
            owner, name = parsed
            key = (owner.lower(), name.lower())
            if key in seen:
                continue
            seen.add(key)
            label = path_m.group(1).strip() if path_m else name
            repos.append({"label": label, "owner": owner, "name": name, "is_parent": False})
    return repos


def build_query(repos: list[dict]) -> str:
    parts = []
    for i, r in enumerate(repos):
        parts.append(
            f'  r{i}: repository(owner: "{r["owner"]}", name: "{r["name"]}") {{\n'
            f"    nameWithOwner\n"
            f"    description\n"
            f"    url\n"
            f"    stargazerCount\n"
            f"    forkCount\n"
            f"    watchers {{ totalCount }}\n"
            f"    issues(states: OPEN) {{ totalCount }}\n"
            f"    pullRequests(states: OPEN) {{ totalCount }}\n"
            f"    pushedAt\n"
            f"    isArchived\n"
            f"    isPrivate\n"
            f"    openGraphImageUrl\n"
            f"    defaultBranchRef {{ name }}\n"
            f"    primaryLanguage {{ name color }}\n"
            f"  }}"
        )
    return "{\n" + "\n".join(parts) + "\n}\n"


def fetch_stats(repos: list[dict]) -> list[dict]:
    query = build_query(repos)
    # gh exits non-zero when the GraphQL response contains `errors`, but the
    # response body still has `data` for the repos that resolved. Don't use
    # run() here — parse stdout ourselves and treat per-repo errors as
    # missing rows rather than a hard failure. This is what lets the
    # workflow succeed when the default GITHUB_TOKEN can't see a private
    # repo listed in .gitmodules.
    result = subprocess.run(
        ["gh", "api", "graphql", "-f", f"query={query}"],
        capture_output=True, text=True, encoding="utf-8",
    )
    try:
        payload = json.loads(result.stdout) if result.stdout else None
    except json.JSONDecodeError:
        payload = None
    if not payload:
        sys.stderr.write(
            f"gh api graphql failed (exit {result.returncode}):\n"
            f"  stdout: {result.stdout[:500]}\n"
            f"  stderr: {result.stderr}\n"
        )
        raise SystemExit(result.returncode or 1)
    if "errors" in payload:
        sys.stderr.write("GraphQL errors (some repos unavailable to this token):\n")
        for e in payload["errors"]:
            sys.stderr.write(f"  - {e.get('type', '?')}: {e.get('message', '')}\n")
    data = payload.get("data") or {}
    rows: list[dict] = []
    for i, r in enumerate(repos):
        node = data.get(f"r{i}")
        if not node:
            rows.append({**r, "missing": True})
            continue
        lang = node.get("primaryLanguage") or {}
        rows.append({
            **r,
            "missing": False,
            "nameWithOwner": node["nameWithOwner"],
            "description": node.get("description") or "",
            "url": node["url"],
            "stars": node["stargazerCount"],
            "forks": node["forkCount"],
            "watchers": node["watchers"]["totalCount"],
            "issues": node["issues"]["totalCount"],
            "prs": node["pullRequests"]["totalCount"],
            "pushedAt": node["pushedAt"],
            "isArchived": node["isArchived"],
            "isPrivate": node.get("isPrivate", False),
            "ogImage": node.get("openGraphImageUrl") or "",
            "defaultBranch": (node.get("defaultBranchRef") or {}).get("name") or "main",
            "language": lang.get("name") or "",
            "languageColor": lang.get("color") or "#888",
        })
    return rows


def _is_badge_url(url: str) -> bool:
    return any(p.search(url) for p in BADGE_PATTERNS)


def _resolve_readme_url(url: str, owner: str, name: str, branch: str) -> str:
    """Turn whatever appears in a README into a fetchable URL."""
    url = url.strip().split("#", 1)[0]
    if not url:
        return ""
    if url.startswith(("http://", "https://")):
        m = re.match(r"https?://github\.com/([^/]+)/([^/]+)/blob/(.+)", url)
        if m:
            return f"https://raw.githubusercontent.com/{m.group(1)}/{m.group(2)}/{m.group(3)}"
        return url
    if url.startswith("./"):
        url = url[2:]
    url = url.lstrip("/")
    encoded = quote(url, safe="/")
    return f"https://raw.githubusercontent.com/{owner}/{name}/{branch}/{encoded}"


def _find_hero_file(repo_dir: Path) -> str:
    """Return the filename of a top-level readme_hero.* file, or ""."""
    if not repo_dir.is_dir():
        return ""
    try:
        for entry in repo_dir.iterdir():
            if entry.is_file() and _HERO_FILE_RE.match(entry.name):
                return entry.name
    except OSError:
        return ""
    return ""


def find_readme_hero(repo_dir: Path, owner: str, name: str, branch: str) -> str:
    """Resolve a hero image URL for the repo.

    Preference order:
      1. A `readme_hero.*` (or README_HERO.*) file at the repo root.
      2. The first non-badge image referenced in the README.
    """
    if not repo_dir.exists() or not repo_dir.is_dir():
        return ""
    hero_file = _find_hero_file(repo_dir)
    if hero_file:
        return _resolve_readme_url(hero_file, owner, name, branch)
    readme_path = next(
        (repo_dir / n for n in _README_NAMES if (repo_dir / n).exists()),
        None,
    )
    if not readme_path:
        return ""
    try:
        text = readme_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    for m in _IMG_RE.finditer(text):
        raw_url = (m.group("md") or m.group("html") or "").strip()
        if not raw_url or _is_badge_url(raw_url):
            continue
        return _resolve_readme_url(raw_url, owner, name, branch)
    return ""


def humanize_pushed(iso: str) -> str:
    dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    delta = datetime.now(timezone.utc) - dt
    seconds = delta.total_seconds()
    if seconds < 3600:
        return f"{int(seconds // 60)}m ago"
    if seconds < 86400:
        return f"{int(seconds // 3600)}h ago"
    days = delta.days
    if days < 30:
        return f"{days}d ago"
    if days < 365:
        return f"{days // 30}mo ago"
    return f"{days // 365}y ago"


def esc(s: str) -> str:
    return (
        str(s)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&#39;")
    )


METRICS = [
    ("stars",     "Stars",     "&#9733;"),  # star
    ("forks",     "Forks",     "&#11119;"), # fork-ish
    ("watchers",  "Watchers",  "&#128065;"), # eye
    ("issues",    "Issues",    "&#9888;"),  # warning
    ("prs",       "PRs",       "&#8644;"),  # arrows
]


def render_html(rows: list[dict], generated_at: datetime) -> str:
    visible = [r for r in rows if not r.get("missing")]
    totals = {k: sum(r[k] for r in visible) for k, _, _ in METRICS}

    # Sort: parent repo first, then by stars desc
    visible.sort(key=lambda r: (not r.get("is_parent"), -r["stars"]))

    rows_html_parts = []
    for r in visible:
        archived_class = " archived" if r["isArchived"] else ""
        parent_badge = '<span class="badge parent">parent</span>' if r.get("is_parent") else ""
        archived_badge = '<span class="badge archived-badge">archived</span>' if r["isArchived"] else ""
        lang_chip = ""
        if r["language"]:
            lang_chip = (
                f'<span class="lang"><span class="lang-dot" '
                f'style="background:{esc(r["languageColor"])}"></span>'
                f'{esc(r["language"])}</span>'
            )
        desc = esc(r["description"]) if r["description"] else '<span class="muted">—</span>'
        pushed_iso = r["pushedAt"]
        pushed_human = humanize_pushed(pushed_iso)
        pushed_epoch = int(datetime.fromisoformat(pushed_iso.replace("Z", "+00:00")).timestamp())
        name_sort = r["label"].lower()
        thumb_html = ""
        if r.get("heroImage"):
            thumb_html = (
                f'<a class="thumb-link" href="{esc(r["url"])}" target="_blank" rel="noopener" aria-hidden="true" tabindex="-1">'
                f'<img class="thumb" src="{esc(r["heroImage"])}" alt="" loading="lazy" '
                f'referrerpolicy="no-referrer" />'
                f'</a>'
            )
        rows_html_parts.append(f"""
        <tr class="repo{archived_class}">
          <td class="name-cell" data-sort="{esc(name_sort)}">
            <div class="name-row">
              {thumb_html}
              <div class="name-text">
                <a class="repo-link" href="{esc(r['url'])}" target="_blank" rel="noopener">
                  <span class="repo-name">{esc(r['label'])}</span>
                  <span class="repo-owner">{esc(r['nameWithOwner'])}</span>
                </a>
                <div class="meta">{parent_badge}{archived_badge}{lang_chip}</div>
                <div class="desc">{desc}</div>
              </div>
            </div>
          </td>
          <td class="num" data-sort="{r['stars']}">{r['stars']:,}</td>
          <td class="num" data-sort="{r['forks']}">{r['forks']:,}</td>
          <td class="num" data-sort="{r['watchers']}">{r['watchers']:,}</td>
          <td class="num" data-sort="{r['issues']}">{r['issues']:,}</td>
          <td class="num" data-sort="{r['prs']}">{r['prs']:,}</td>
          <td class="num pushed" data-sort="{pushed_epoch}" title="{esc(pushed_iso)}">{esc(pushed_human)}</td>
        </tr>""")

    missing_html = ""
    missing = [r for r in rows if r.get("missing")]
    if missing:
        items = "".join(
            f"<li>{esc(r['owner'])}/{esc(r['name'])}</li>" for r in missing
        )
        missing_html = (
            f'<div class="warn">Could not fetch: <ul>{items}</ul></div>'
        )

    summary_cards = "".join(
        f"""
        <div class="card">
          <div class="card-icon">{icon}</div>
          <div class="card-value">{totals[key]:,}</div>
          <div class="card-label">{esc(label)}</div>
        </div>"""
        for key, label, icon in METRICS
    )

    generated_str = generated_at.strftime("%Y-%m-%d %H:%M UTC")
    repo_count = len(visible)

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8" />
<title>rust-apps &mdash; repo stats</title>
<meta name="viewport" content="width=device-width, initial-scale=1" />
<style>
  :root {{
    --bg: #f7f8fa;
    --panel: #ffffff;
    --text: #1a1f29;
    --muted: #6b7280;
    --border: #e5e7eb;
    --accent: #ea580c;
    --accent-soft: #fff1e7;
    --row-hover: #fafbfd;
    --shadow: 0 1px 2px rgba(20, 24, 32, 0.04), 0 4px 16px rgba(20, 24, 32, 0.04);
    --badge-bg: #eef2ff;
    --badge-fg: #3730a3;
    --archived-bg: #fef3c7;
    --archived-fg: #92400e;
  }}
  @media (prefers-color-scheme: dark) {{
    :root {{
      --bg: #0d1117;
      --panel: #161b22;
      --text: #e6edf3;
      --muted: #8b949e;
      --border: #30363d;
      --accent: #f97316;
      --accent-soft: #2a1a0d;
      --row-hover: #1c222b;
      --shadow: 0 1px 2px rgba(0,0,0,0.4), 0 4px 16px rgba(0,0,0,0.3);
      --badge-bg: #1e2a4a;
      --badge-fg: #a5b4fc;
      --archived-bg: #3b2a0c;
      --archived-fg: #fbbf24;
    }}
  }}
  * {{ box-sizing: border-box; }}
  html, body {{ margin: 0; padding: 0; }}
  body {{
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue",
                 Arial, "Noto Sans", sans-serif, "Apple Color Emoji", "Segoe UI Emoji";
    background: var(--bg);
    color: var(--text);
    line-height: 1.5;
    -webkit-font-smoothing: antialiased;
  }}
  .wrap {{ max-width: 1180px; margin: 0 auto; padding: 32px 24px 64px; }}
  header.page {{
    display: flex; align-items: baseline; justify-content: space-between;
    flex-wrap: wrap; gap: 12px; margin-bottom: 24px;
  }}
  h1 {{
    font-size: 28px; font-weight: 700; letter-spacing: -0.02em; margin: 0;
  }}
  h1 .accent {{ color: var(--accent); }}
  .subtitle {{ color: var(--muted); font-size: 14px; }}
  .summary {{
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
    gap: 12px;
    margin-bottom: 28px;
  }}
  .card {{
    background: var(--panel);
    border: 1px solid var(--border);
    border-radius: 12px;
    padding: 16px 18px;
    box-shadow: var(--shadow);
    display: flex; flex-direction: column; gap: 4px;
    position: relative; overflow: hidden;
  }}
  .card::before {{
    content: ""; position: absolute; inset: 0 0 auto 0; height: 3px;
    background: linear-gradient(90deg, var(--accent), transparent 80%);
    opacity: 0.85;
  }}
  .card-icon {{ font-size: 18px; color: var(--accent); }}
  .card-value {{ font-size: 26px; font-weight: 700; letter-spacing: -0.02em; }}
  .card-label {{ font-size: 12px; color: var(--muted); text-transform: uppercase; letter-spacing: 0.06em; }}
  .panel {{
    background: var(--panel);
    border: 1px solid var(--border);
    border-radius: 12px;
    box-shadow: var(--shadow);
    overflow: hidden;
  }}
  table {{ width: 100%; border-collapse: collapse; }}
  thead th {{
    text-align: left;
    font-size: 12px;
    text-transform: uppercase;
    letter-spacing: 0.06em;
    color: var(--muted);
    font-weight: 600;
    padding: 14px 16px;
    border-bottom: 1px solid var(--border);
    background: var(--panel);
    position: sticky; top: 0;
    cursor: pointer;
    user-select: none;
    white-space: nowrap;
  }}
  thead th.num {{ text-align: right; }}
  thead th:hover {{ color: var(--text); }}
  thead th .sort-ind {{ font-size: 10px; margin-left: 4px; opacity: 0.6; }}
  tbody td {{
    padding: 16px;
    border-bottom: 1px solid var(--border);
    vertical-align: top;
  }}
  tbody tr:last-child td {{ border-bottom: none; }}
  tbody tr:hover {{ background: var(--row-hover); }}
  tr.archived td {{ opacity: 0.65; }}
  .name-cell {{ min-width: 320px; }}
  .name-row {{ display: flex; align-items: flex-start; gap: 14px; }}
  .name-text {{ min-width: 0; flex: 1; }}
  .thumb-link {{ flex: 0 0 auto; display: block; }}
  .thumb {{
    width: 96px; height: 48px; object-fit: cover; border-radius: 6px;
    border: 1px solid var(--border); background: var(--row-hover);
    display: block;
  }}
  .repo-link {{ text-decoration: none; color: var(--text); display: flex; align-items: baseline; gap: 8px; flex-wrap: wrap; }}
  .repo-link:hover .repo-name {{ color: var(--accent); }}
  .repo-name {{ font-size: 16px; font-weight: 600; letter-spacing: -0.01em; }}
  .repo-owner {{ font-size: 12px; color: var(--muted); }}
  .desc {{ font-size: 13px; color: var(--muted); margin-top: 6px; }}
  .meta {{ display: flex; gap: 6px; flex-wrap: wrap; margin-top: 6px; }}
  .badge {{
    display: inline-block;
    font-size: 10px;
    text-transform: uppercase;
    letter-spacing: 0.06em;
    padding: 2px 8px;
    border-radius: 999px;
    font-weight: 600;
  }}
  .badge.parent {{ background: var(--accent-soft); color: var(--accent); }}
  .badge.archived-badge {{ background: var(--archived-bg); color: var(--archived-fg); }}
  .lang {{ display: inline-flex; align-items: center; gap: 6px; font-size: 12px; color: var(--muted); }}
  .lang-dot {{ width: 10px; height: 10px; border-radius: 50%; display: inline-block; }}
  td.num {{ text-align: right; font-variant-numeric: tabular-nums; font-weight: 500; white-space: nowrap; }}
  td.pushed {{ color: var(--muted); font-weight: 400; }}
  .muted {{ color: var(--muted); }}
  .warn {{
    margin-top: 16px; padding: 12px 16px; border-radius: 10px;
    background: var(--archived-bg); color: var(--archived-fg); font-size: 13px;
  }}
  .warn ul {{ margin: 4px 0 0; padding-left: 18px; }}
  footer {{ color: var(--muted); font-size: 12px; margin-top: 24px; text-align: center; }}
  footer a {{ color: var(--muted); }}
  @media (max-width: 720px) {{
    thead th:not(:first-child) {{ padding: 12px 8px; }}
    tbody td:not(:first-child) {{ padding: 12px 8px; }}
    .desc {{ display: none; }}
    .thumb {{ width: 64px; height: 32px; }}
  }}
</style>
</head>
<body>
<div class="wrap">
  <header class="page">
    <div>
      <h1><span class="accent">rust-apps</span> &middot; repo stats</h1>
      <div class="subtitle">{repo_count} repositories &middot; generated {esc(generated_str)}</div>
    </div>
  </header>

  <section class="summary">
    {summary_cards}
  </section>

  <section class="panel">
    <table id="repos">
      <thead>
        <tr>
          <th data-key="label">Repository <span class="sort-ind"></span></th>
          <th class="num" data-key="stars">&#9733; Stars <span class="sort-ind">&#9660;</span></th>
          <th class="num" data-key="forks">&#11119; Forks <span class="sort-ind"></span></th>
          <th class="num" data-key="watchers">&#128065; Watchers <span class="sort-ind"></span></th>
          <th class="num" data-key="issues">&#9888; Issues <span class="sort-ind"></span></th>
          <th class="num" data-key="prs">&#8644; PRs <span class="sort-ind"></span></th>
          <th class="num" data-key="pushed">Pushed <span class="sort-ind"></span></th>
        </tr>
      </thead>
      <tbody>
        {''.join(rows_html_parts)}
      </tbody>
    </table>
  </section>

  {missing_html}

  <footer>
    Data via GitHub GraphQL API &middot;
    <a href="https://github.com/larsbrubaker/rust-apps" target="_blank" rel="noopener">larsbrubaker/rust-apps</a>
  </footer>
</div>
<script>
  (function() {{
    const table = document.getElementById('repos');
    if (!table) return;
    const tbody = table.tBodies[0];
    const headers = table.tHead.rows[0].cells;
    let activeCol = 1, activeDir = -1; // start sorted by stars desc

    function sortBy(col, dir) {{
      const rows = Array.from(tbody.rows);
      rows.sort((a, b) => {{
        const av = a.cells[col].dataset.sort ?? a.cells[col].textContent.trim();
        const bv = b.cells[col].dataset.sort ?? b.cells[col].textContent.trim();
        const an = parseFloat(av), bn = parseFloat(bv);
        if (!isNaN(an) && !isNaN(bn)) return (an - bn) * dir;
        return av.localeCompare(bv) * dir;
      }});
      rows.forEach(r => tbody.appendChild(r));
      for (let i = 0; i < headers.length; i++) {{
        const ind = headers[i].querySelector('.sort-ind');
        if (ind) ind.textContent = (i === col) ? (dir === 1 ? '\\u25B2' : '\\u25BC') : '';
      }}
    }}

    Array.from(headers).forEach((th, i) => {{
      th.addEventListener('click', () => {{
        if (i === activeCol) activeDir = -activeDir;
        else {{ activeCol = i; activeDir = (i === 0) ? 1 : -1; }}
        sortBy(activeCol, activeDir);
      }});
    }});
  }})();
</script>
</body>
</html>
"""


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", default=str(REPO_ROOT / "repo_stats.html"),
                    help="Output HTML path (default: repo_stats.html next to script)")
    ap.add_argument("--json", action="store_true",
                    help="Also write a JSON snapshot next to the HTML")
    ap.add_argument("--root", default=str(REPO_ROOT),
                    help="Path to the rust-apps checkout (default: script directory)")
    args = ap.parse_args(argv)

    root = Path(args.root).resolve()
    repos = discover_repos(root)
    if not repos:
        sys.stderr.write("No repos discovered. Is this a git checkout with submodules?\n")
        return 1

    print(f"Querying GitHub for {len(repos)} repo(s)...", file=sys.stderr)
    rows = fetch_stats(repos)

    private = [r for r in rows if r.get("isPrivate")]
    if private:
        names = ", ".join(f"{r['owner']}/{r['name']}" for r in private)
        print(f"Skipping {len(private)} private repo(s): {names}", file=sys.stderr)
        rows = [r for r in rows if not r.get("isPrivate")]

    for r in rows:
        if r.get("missing"):
            continue
        repo_dir = root if r.get("is_parent") else root / r["label"]
        hero = find_readme_hero(repo_dir, r["owner"], r["name"], r.get("defaultBranch") or "main")
        r["heroImage"] = hero or r.get("ogImage") or ""
        r["heroSource"] = "readme" if hero else ("og" if r.get("ogImage") else "none")

    generated_at = datetime.now(timezone.utc)

    out_path = Path(args.out).resolve()
    out_path.write_text(render_html(rows, generated_at), encoding="utf-8")
    print(f"Wrote {out_path}", file=sys.stderr)

    if args.json:
        json_path = out_path.with_suffix(".json")
        json_path.write_text(
            json.dumps({"generatedAt": generated_at.isoformat(), "repos": rows}, indent=2),
            encoding="utf-8",
        )
        print(f"Wrote {json_path}", file=sys.stderr)

    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
