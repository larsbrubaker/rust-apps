#!/usr/bin/env python3
"""Publish updated crates to crates.io and push every rust-apps repo.

Workflow (run AFTER version bumps and release notes are committed locally
in each submodule, and the superproject pointer commit exists locally):

1. For each crate submodule, in dependency order, compare the local
   Cargo.toml version against the version published on crates.io.
2. If the local version is newer: verify sibling dependency requirements
   match, `cargo publish --dry-run`, then `cargo publish`, then poll
   crates.io until the new version is indexed (so dependents can build),
   then tag `vX.Y.Z`.
3. Push each submodule (branch + tags) only after its publish succeeded,
   so GitHub never shows a release that failed to reach crates.io.
4. Push the superproject last, once every submodule pointer it references
   is public.

The crates.io token is read from the CARGO_REGISTRY_TOKEN environment
variable, or prompted for interactively (hidden input). It is passed to
cargo via the environment only — never echoed, logged, or written to disk.

Usage:
    python publish_all.py             # full run (asks for confirmation)
    python publish_all.py --dry-run   # rehearse: no publish, no push, no tag
    python publish_all.py --yes       # skip the confirmation prompt
    python publish_all.py --only agg-rust box2d-rust   # limit to some repos
"""
from __future__ import annotations

import argparse
import getpass
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

try:
    import tomllib  # Python 3.11+
except ModuleNotFoundError:  # pragma: no cover
    sys.exit("Python 3.11+ is required (tomllib).")

REPO_ROOT = Path(__file__).resolve().parent
USER_AGENT = "rust-apps-publish-script (larsbrubaker@gmail.com)"
INDEX_POLL_SECONDS = 5
INDEX_TIMEOUT_SECONDS = 600


@dataclass
class Repo:
    """One submodule. `crate_dir` is relative to the submodule root and
    holds the publishable Cargo.toml; None means push-only (no crate)."""

    name: str
    crate_dir: str | None = "."
    # Sibling crates this one depends on from crates.io; their published
    # versions must match the local sibling checkouts before we publish.
    depends_on: list[str] = field(default_factory=list)

    @property
    def path(self) -> Path:
        return REPO_ROOT / self.name

    @property
    def manifest(self) -> Path | None:
        if self.crate_dir is None:
            return None
        return self.path / self.crate_dir / "Cargo.toml"


# Dependency order: everything agg-gui consumes publishes before agg-gui.
REPOS: list[Repo] = [
    Repo("agg-rust"),
    Repo("clipper2-rust"),
    Repo("tess2-rust"),
    Repo("manifold-rust"),
    Repo("agg-gui", crate_dir="agg-gui",
         depends_on=["agg-rust", "clipper2-rust", "tess2-rust"]),
    Repo("box2d-rust"),
    Repo("box3d-rust"),
    Repo("atomartist", crate_dir=None),
]


def run(cmd: list[str], cwd: Path, *, env: dict[str, str] | None = None,
        check: bool = True, capture: bool = True) -> subprocess.CompletedProcess:
    result = subprocess.run(
        cmd, cwd=cwd, env=env, text=True, encoding="utf-8", errors="replace",
        capture_output=capture,
    )
    if check and result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip() if capture else ""
        raise RuntimeError(
            f"command failed ({result.returncode}) in {cwd}:\n"
            f"  {' '.join(cmd)}\n{detail}"
        )
    return result


def git(repo: Path, *args: str, check: bool = True) -> str:
    return run(["git", *args], cwd=repo, check=check).stdout.strip()


def load_toml(path: Path) -> dict:
    # utf-8-sig tolerates a UTF-8 BOM (common in files written on Windows),
    # which tomllib.load on a binary handle rejects.
    return tomllib.loads(path.read_text(encoding="utf-8-sig"))


def parse_version(text: str) -> tuple[int, ...]:
    core = text.split("-")[0].split("+")[0]
    return tuple(int(p) for p in core.split("."))


def local_crate_info(repo: Repo) -> tuple[str, str]:
    """Return (crate name, version) from the repo's publishable manifest."""
    assert repo.manifest is not None
    data = load_toml(repo.manifest)
    pkg = data["package"]
    return pkg["name"], pkg["version"]


def crates_io_get(url: str) -> dict | None:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        raise


def published_version(crate: str) -> str | None:
    data = crates_io_get(f"https://crates.io/api/v1/crates/{crate}")
    if data is None:
        return None
    return data["crate"]["max_version"]


def wait_for_index(crate: str, version: str) -> None:
    print(f"    waiting for crates.io to index {crate} {version} ...")
    deadline = time.monotonic() + INDEX_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        data = crates_io_get(f"https://crates.io/api/v1/crates/{crate}/{version}")
        if data is not None:
            print(f"    indexed.")
            return
        time.sleep(INDEX_POLL_SECONDS)
    raise RuntimeError(f"{crate} {version} not indexed after "
                       f"{INDEX_TIMEOUT_SECONDS}s; resolve manually and re-run.")


def check_sibling_requirements(repo: Repo, locals_: dict[str, str]) -> None:
    """Fail if repo's Cargo.toml requires an older sibling version than the
    one we are publishing (dependents must pick up the new releases)."""
    assert repo.manifest is not None
    data = load_toml(repo.manifest)
    deps = data.get("dependencies", {})
    problems = []
    for sib in repo.depends_on:
        req = deps.get(sib)
        if req is None:
            continue
        req_str = req if isinstance(req, str) else req.get("version", "")
        want = locals_[sib]
        # Requirement like "1.0.3" (caret) must equal the sibling's local
        # version exactly so docs and lockfiles point at the new release.
        if req_str.lstrip("^") != want:
            problems.append(f"{sib}: requires '{req_str}', local sibling is {want}")
    if problems:
        raise RuntimeError(
            f"{repo.name} has stale sibling requirements:\n  " + "\n  ".join(problems)
        )


def repo_state(repo: Repo) -> dict:
    """Gather what needs doing for one repo."""
    state: dict = {"repo": repo}
    if not repo.path.exists() or not (repo.path / ".git").exists():
        state["skip"] = "not checked out"
        return state
    dirty = git(repo.path, "status", "--porcelain", "--untracked-files=no")
    state["dirty"] = dirty
    branch = git(repo.path, "rev-parse", "--abbrev-ref", "HEAD")
    state["branch"] = branch
    ahead = git(repo.path, "rev-list", "--count", f"origin/{branch}..HEAD",
                check=False) or "0"
    state["ahead"] = int(ahead)

    if repo.manifest is not None:
        crate, local_v = local_crate_info(repo)
        pub_v = published_version(crate)
        state.update(crate=crate, local=local_v, published=pub_v)
        if pub_v is None:
            state["publish"] = True  # brand-new crate
        else:
            lv, pv = parse_version(local_v), parse_version(pub_v)
            if lv > pv:
                state["publish"] = True
            elif lv == pv:
                state["publish"] = False
            else:
                raise RuntimeError(
                    f"{crate}: local {local_v} is OLDER than published {pub_v}")
    else:
        state["publish"] = False
    return state


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--dry-run", action="store_true",
                    help="verify everything but do not publish, tag, or push")
    ap.add_argument("--yes", action="store_true",
                    help="skip the confirmation prompt")
    ap.add_argument("--only", nargs="*", metavar="REPO",
                    help="limit to these submodule names")
    args = ap.parse_args()

    repos = [r for r in REPOS if not args.only or r.name in args.only]

    # ---- Plan ----------------------------------------------------------
    print("Inspecting repos ...")
    states = []
    locals_: dict[str, str] = {}
    for repo in repos:
        st = repo_state(repo)
        states.append(st)
        if "crate" in st:
            locals_[st["crate"]] = st["local"]

    print()
    print(f"{'repo':<16} {'crate version':<22} {'action'}")
    print("-" * 60)
    blockers = []
    for st in states:
        repo = st["repo"]
        if st.get("skip"):
            print(f"{repo.name:<16} {'-':<22} skipped ({st['skip']})")
            continue
        if "crate" in st:
            ver = f"{st['published'] or 'unpublished'} -> {st['local']}"
        else:
            ver = "-"
        actions = []
        if st["publish"]:
            actions.append("publish")
        if st["ahead"]:
            actions.append(f"push {st['ahead']} commit(s)")
        if st["dirty"]:
            blockers.append(f"{repo.name} has uncommitted changes:\n{st['dirty']}")
        print(f"{repo.name:<16} {ver:<22} {', '.join(actions) or 'up to date'}")

    super_ahead = int(git(REPO_ROOT, "rev-list", "--count",
                          "origin/main..HEAD", check=False) or "0")
    super_dirty = git(REPO_ROOT, "status", "--porcelain", "--untracked-files=no")
    print(f"{'<superproject>':<16} {'-':<22} "
          f"{f'push {super_ahead} commit(s)' if super_ahead else 'up to date'}")
    if super_dirty:
        blockers.append(f"superproject has uncommitted changes:\n{super_dirty}")
    print()

    if blockers:
        print("Cannot continue -- commit or stash these first:\n")
        print("\n\n".join(blockers))
        return 1

    to_publish = [st for st in states if st.get("publish")]
    if not to_publish and not any(st.get("ahead") for st in states) and not super_ahead:
        print("Nothing to do.")
        return 0

    if args.dry_run:
        print("--dry-run: running cargo publish --dry-run for each crate, "
              "no tags or pushes.\n")
    elif not args.yes:
        answer = input("Proceed with publish + push? [yes/no] ").strip().lower()
        if answer not in ("y", "yes"):
            print("Aborted.")
            return 1

    # ---- Token ---------------------------------------------------------
    env = os.environ.copy()
    if to_publish and not env.get("CARGO_REGISTRY_TOKEN"):
        token = getpass.getpass("crates.io API token (input hidden): ").strip()
        if not token and not args.dry_run:
            print("No token provided.")
            return 1
        if token:
            env["CARGO_REGISTRY_TOKEN"] = token

    # ---- Execute -------------------------------------------------------
    for st in states:
        repo = st["repo"]
        if st.get("skip"):
            continue
        print(f"\n=== {repo.name} ===")

        if st["publish"]:
            check_sibling_requirements(repo, locals_)
            crate, version = st["crate"], st["local"]
            crate_cwd = repo.path / (repo.crate_dir or ".")

            # In rehearsal mode, sibling deps haven't actually been published,
            # so a dependent crate cannot resolve them — skip its dry-run.
            publishing_now = {s["crate"] for s in states
                             if s.get("publish") and s is not st}
            if args.dry_run and publishing_now & set(repo.depends_on):
                print(f"  skipping cargo publish --dry-run for {crate}: "
                      f"depends on sibling(s) not yet on crates.io")
                continue

            print(f"  cargo publish --dry-run ({crate} {version})")
            run(["cargo", "publish", "--dry-run", "-p", crate],
                cwd=crate_cwd, env=env, capture=False)

            if not args.dry_run:
                print(f"  cargo publish ({crate} {version})")
                run(["cargo", "publish", "-p", crate],
                    cwd=crate_cwd, env=env, capture=False)
                wait_for_index(crate, version)

                tag = f"v{version}"
                existing = git(repo.path, "tag", "-l", tag)
                if not existing:
                    git(repo.path, "tag", "-a", tag, "-m", f"{crate} {version}")
                    print(f"  tagged {tag}")

        if not args.dry_run:
            branch = st["branch"]
            if st["ahead"]:
                print(f"  pushing {branch} ({st['ahead']} commit(s))")
            git(repo.path, "push", "origin", branch, "--follow-tags")

    if not args.dry_run:
        print("\n=== superproject ===")
        if super_ahead:
            print(f"  pushing main ({super_ahead} commit(s))")
        git(REPO_ROOT, "push", "origin", "main")

    print("\nDone." if not args.dry_run else "\nDry run complete.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(130)
    except RuntimeError as e:
        print(f"\nERROR: {e}", file=sys.stderr)
        sys.exit(1)
