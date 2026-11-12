"""Command-line interface."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from typing import List, Optional

from . import __version__
from .checks import OK, STALE, UNCHECKED, Repo, Result, check
from .extract import discover, extract


def git_root(start: str) -> str:
    try:
        out = subprocess.run(["git", "-C", start, "rev-parse", "--show-toplevel"], capture_output=True, text=True, timeout=10)
        if out.returncode == 0 and out.stdout.strip():
            return out.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        pass
    return os.path.abspath(start)


def scan(root: str, files: Optional[List[str]] = None) -> List[Result]:
    repo = Repo(root)
    paths = [os.path.abspath(f) for f in files] if files else discover(repo.root)
    results = []
    seen = set()
    for p in paths:
        for ref in extract(p, repo.root):
            key = (ref.file, ref.line, ref.kind, ref.text)
            if key in seen:
                continue
            seen.add(key)
            results.append(check(ref, repo))
    return results


ICON = {OK: "ok   ", STALE: "STALE", UNCHECKED: "skip "}


def render_text(results: List[Result], show_all: bool, files: List[str]) -> str:
    out = []
    shown = [r for r in results if show_all or r.status == STALE]
    for r in shown:
        line = f"{ICON[r.status]} {r.ref.file}:{r.ref.line}  {r.ref.text}"
        out.append(line)
        detail = r.reason + (f" ({r.hint})" if r.hint else "")
        out.append(f"      {detail}")
    counts = {s: sum(1 for r in results if r.status == s) for s in (OK, STALE, UNCHECKED)}
    if out:
        out.append("")
    out.append(
        f"{len(files)} instruction file(s), {len(results)} reference(s): "
        f"{counts[STALE]} stale, {counts[OK]} ok, {counts[UNCHECKED]} unchecked"
    )
    return "\n".join(out)


def render_github(results: List[Result]) -> str:
    out = []
    for r in results:
        if r.status != STALE:
            continue
        msg = f"{r.ref.text}: {r.reason}" + (f" ({r.hint})" if r.hint else "")
        msg = msg.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")
        out.append(f"::warning file={r.ref.file},line={r.ref.line},title=stalemd::{msg}")
    return "\n".join(out)


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        prog="stalemd",
        description="Find the commands, scripts and paths in AGENTS.md, CLAUDE.md and other agent "
        "instruction files that no longer exist in the repo.",
    )
    ap.add_argument("files", nargs="*", help="instruction files to check (default: discover under --root)")
    ap.add_argument("--root", help="repository root (default: git top level of the current dir)")
    ap.add_argument("--format", choices=["text", "json", "github"], default="text")
    ap.add_argument("--all", action="store_true", help="also list references that check out or were skipped")
    ap.add_argument("--no-fail", action="store_true", help="exit 0 even when stale references are found")
    ap.add_argument("--list-files", action="store_true", help="print the instruction files that would be scanned")
    ap.add_argument("--version", action="version", version=f"stalemd {__version__}")
    args = ap.parse_args(argv)

    root = os.path.abspath(args.root) if args.root else git_root(".")
    files = [os.path.abspath(f) for f in args.files] if args.files else discover(root)
    for f in files:
        if not os.path.isfile(f):
            print(f"stalemd: no such file: {f}", file=sys.stderr)
            return 2
    if args.list_files:
        for f in files:
            print(os.path.relpath(f, root))
        return 0

    results = scan(root, files)
    if args.format == "json":
        print(json.dumps({"files": [os.path.relpath(f, root) for f in files], "results": [r.to_dict() for r in results]}, indent=2))
    elif args.format == "github":
        text = render_github(results)
        if text:
            print(text)
        print(render_text(results, False, files).splitlines()[-1])
    else:
        print(render_text(results, args.all, files))
    stale = any(r.status == STALE for r in results)
    return 1 if stale and not args.no_fail else 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
