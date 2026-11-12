"""Check extracted references against the repository on disk."""

from __future__ import annotations

import difflib
import glob
import json
import os
import re
import shlex
import subprocess
from dataclasses import dataclass
from typing import Dict, List, Optional

from .extract import SKIP_DIRS, Ref

OK, STALE, UNCHECKED = "ok", "stale", "unchecked"

NPM_BUILTINS = {
    "install", "i", "ci", "add", "remove", "rm", "uninstall", "update", "up", "exec", "x", "dlx",
    "publish", "pack", "link", "init", "create", "audit", "outdated", "ls", "list", "why", "info",
    "view", "login", "logout", "config", "set", "cache", "prune", "dedupe", "version", "help",
    "upgrade", "import", "store", "env", "setup", "rebuild", "fetch", "patch", "-v", "--version",
}
BUN_BUILTINS = NPM_BUILTINS | {"test", "build", "x", "repl", "pm"}


@dataclass
class Result:
    ref: Ref
    status: str
    reason: str
    hint: str = ""

    def to_dict(self) -> dict:
        return {
            "file": self.ref.file,
            "line": self.ref.line,
            "kind": self.ref.kind,
            "text": self.ref.text,
            "status": self.status,
            "reason": self.reason,
            "hint": self.hint,
        }


def _in_git(path: str) -> bool:
    try:
        r = subprocess.run(["git", "-C", path, "rev-parse", "--is-inside-work-tree"], capture_output=True, text=True, timeout=10)
        return r.returncode == 0 and r.stdout.strip() == "true"
    except (OSError, subprocess.SubprocessError):
        return False


class Repo:
    """Lazy, cached view of the repository on disk."""

    def __init__(self, root: str):
        self.root = os.path.abspath(root)
        self._files: Optional[List[str]] = None
        self._pkg: Dict[str, Optional[dict]] = {}
        self._targets: Dict[str, Optional[set]] = {}
        self._ignored: Dict[str, bool] = {}
        self._git = _in_git(self.root)

    # -- file index -------------------------------------------------------
    def files(self) -> List[str]:
        if self._files is None:
            out = []
            for dirpath, dirnames, filenames in os.walk(self.root):
                dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
                for name in filenames + dirnames:
                    out.append(os.path.relpath(os.path.join(dirpath, name), self.root).replace(os.sep, "/"))
            self._files = sorted(out)
        return self._files

    def suggest_path(self, missing: str) -> str:
        name = missing.rstrip("/").rsplit("/", 1)[-1]
        same = [f for f in self.files() if f.rsplit("/", 1)[-1] == name]
        if same:
            return "found at " + ", ".join(same[:3])
        close = difflib.get_close_matches(missing.rstrip("/"), self.files(), n=1, cutoff=0.8)
        return f"did you mean {close[0]}?" if close else ""

    def inside(self, path: str) -> bool:
        real = os.path.realpath(path)
        return real == self.root or real.startswith(self.root + os.sep)

    def is_ignored(self, path: str, is_dir: bool = False) -> bool:
        """True when git ignores the path (build output, local env files, ...)."""
        if is_dir and not path.endswith("/"):
            path += "/"
        if not self._git:
            parts = os.path.relpath(path, self.root).split(os.sep)
            return any(p in SKIP_DIRS for p in parts)
        if path not in self._ignored:
            try:
                r = subprocess.run(
                    ["git", "-C", self.root, "check-ignore", "-q", "--no-index", path],
                    capture_output=True,
                    timeout=10,
                )
                self._ignored[path] = r.returncode == 0
            except (OSError, subprocess.SubprocessError):
                self._ignored[path] = False
        return self._ignored[path]

    # -- manifests --------------------------------------------------------
    def find_up(self, start: str, names) -> Optional[str]:
        d = os.path.abspath(start)
        while True:
            for n in names:
                p = os.path.join(d, n)
                if os.path.isfile(p):
                    return p
            if d == self.root or not d.startswith(self.root) or os.path.dirname(d) == d:
                return None
            d = os.path.dirname(d)

    def package_json(self, start: str) -> Optional[dict]:
        p = self.find_up(start, ["package.json"])
        if p is None:
            return None
        if p not in self._pkg:
            try:
                with open(p, encoding="utf-8") as fh:
                    data = json.load(fh)
                data["__path__"] = p
                self._pkg[p] = data
            except (OSError, ValueError):
                self._pkg[p] = None
        return self._pkg[p]

    def make_targets(self, makefile: str) -> Optional[set]:
        if makefile not in self._targets:
            targets = set()
            includes = False
            try:
                with open(makefile, encoding="utf-8", errors="replace") as fh:
                    for line in fh:
                        if re.match(r"^-?include\s", line):
                            includes = True
                        m = re.match(r"^([A-Za-z0-9_.%/$(){}\-][^:=#\t]*?)\s*::?(?!=)", line)
                        if m and not line.startswith("\t"):
                            for t in m.group(1).split():
                                targets.add(t)
            except OSError:
                targets = None
            self._targets[makefile] = (targets, includes)
        return self._targets[makefile]

    def just_recipes(self, justfile: str) -> set:
        out = set()
        with open(justfile, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                m = re.match(r"^@?([A-Za-z0-9_-]+)(?:\s+[^:=]*)?:(?!=)", line)
                if m and not line.startswith((" ", "\t")):
                    out.add(m.group(1))
                a = re.match(r"^alias\s+([A-Za-z0-9_-]+)\s*:=", line)
                if a:
                    out.add(a.group(1))
        return out


# -- path checks ------------------------------------------------------------
PLACEHOLDER_HINTS = ("path/to", "your-", "your_", "<", ">", "...", "xxx", "foo/bar", "example/")


def check_path(ref: Ref, repo: Repo, text: Optional[str] = None, base: Optional[str] = None) -> Result:
    target = (text or ref.text).strip()
    base = base or ref.base
    if any(h in target.lower() for h in PLACEHOLDER_HINTS):
        return Result(ref, UNCHECKED, "looks like a placeholder")
    is_glob = any(ch in target for ch in "*?[")
    if target.startswith("/"):
        candidates = [os.path.join(repo.root, target.lstrip("/"))]
    else:
        candidates = [os.path.normpath(os.path.join(base, target))]
        if base != repo.root:
            candidates.append(os.path.normpath(os.path.join(repo.root, target)))
    for c in candidates:
        if is_glob:
            pattern = c if "/" in target else os.path.join(os.path.dirname(c), "**", target)
            if glob.glob(pattern, recursive=True):
                return Result(ref, OK, "glob matches")
        elif os.path.exists(c):
            return Result(ref, OK, "exists")
    first = candidates[0]
    if not repo.inside(first):
        return Result(ref, UNCHECKED, "points outside the repository")
    if repo.is_ignored(first, target.endswith("/")):
        return Result(ref, UNCHECKED, "missing but git-ignored (generated or local file)")
    clean = target.rstrip("/").lstrip("./")
    if is_glob:
        return Result(ref, STALE, "glob matches nothing")
    # Written relative to some subdirectory (e.g. `src/cli/x.ts` inside packages/foo)?
    suffix = [f for f in repo.files() if f == clean or f.endswith("/" + clean)]
    if suffix:
        return Result(ref, OK, f"matches {suffix[0]}" + (f" (+{len(suffix) - 1} more)" if len(suffix) > 1 else ""))
    if "/" not in clean:
        if clean.lower().endswith(".md") and ref.origin != "import":
            return Result(ref, STALE, "file not found anywhere in the repository", repo.suggest_path(target))
        if ref.origin in ("link", "import"):
            return Result(ref, STALE, "linked file does not exist", repo.suggest_path(target))
        return Result(ref, UNCHECKED, "bare file name not found in the repository (may live outside it)")
    head = clean.split("/", 1)[0]
    last = clean.rsplit("/", 1)[-1]
    has_ext = "." in last and not last.startswith(".")
    if not has_ext and not target.endswith("/") and ref.origin == "inline":
        if not any(f == head or f.endswith("/" + head) for f in repo.files()):
            return Result(ref, UNCHECKED, f"`{head}` isn't in the repository; may not be a path")
    return Result(ref, STALE, "path does not exist", repo.suggest_path(target))


# -- command checks ---------------------------------------------------------
SPLIT_RE = re.compile(r"\s*(?:&&|\|\||;|\|)\s*")


def split_chain(cmd: str) -> List[str]:
    return [p for p in SPLIT_RE.split(cmd) if p.strip()]


def _tokens(part: str) -> Optional[List[str]]:
    try:
        toks = shlex.split(part, comments=True)
    except ValueError:
        return None
    while toks and re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", toks[0]):
        toks.pop(0)
    return toks


def _script_check(ref: Ref, repo: Repo, base: str, script: str, tool: str) -> Result:
    pkg = repo.package_json(base)
    if pkg is None:
        return Result(ref, STALE, f"`{tool}` script `{script}` but no package.json found")
    scripts = pkg.get("scripts") or {}
    if script in scripts:
        return Result(ref, OK, f"script `{script}` in {os.path.relpath(pkg['__path__'], repo.root)}")
    if tool == "npm" and script == "start" and os.path.exists(os.path.join(os.path.dirname(pkg["__path__"]), "server.js")):
        return Result(ref, OK, "npm start falls back to server.js")
    close = difflib.get_close_matches(script, list(scripts), n=1, cutoff=0.6)
    hint = f"did you mean `{close[0]}`?" if close else (f"scripts: {', '.join(sorted(scripts))}" if scripts else "package.json has no scripts")
    return Result(ref, STALE, f"no script `{script}` in {os.path.relpath(pkg['__path__'], repo.root)}", hint)


def _node_runner(ref, repo, base, toks) -> Result:
    tool = toks[0]
    args = [t for t in toks[1:]]
    scoped = ("--filter", "-F", "--workspace", "-w", "--cwd", "--prefix", "-C", "workspace", "workspaces", "--dir", "-r", "--recursive")
    if any(a in scoped or a.split("=", 1)[0] in scoped for a in args):
        return Result(ref, UNCHECKED, "workspace-scoped command")
    positional = [a for a in args if not a.startswith("-")]
    if not positional:
        if tool in ("yarn", "pnpm", "bun") and repo.package_json(base) is None:
            return Result(ref, STALE, f"`{tool}` but no package.json found")
        return Result(ref, OK, "package manager builtin")
    sub = positional[0]
    if tool == "npm":
        if sub in ("run", "run-script", "rum", "urn"):
            if len(positional) < 2:
                return Result(ref, OK, "lists scripts")
            return _script_check(ref, repo, base, positional[1], tool)
        if sub in ("test", "t", "tst", "start", "stop", "restart"):
            name = {"t": "test", "tst": "test"}.get(sub, sub)
            return _script_check(ref, repo, base, name, tool)
        if sub in NPM_BUILTINS:
            return Result(ref, OK, "npm builtin")
        return Result(ref, UNCHECKED, f"unknown npm subcommand `{sub}`")
    builtins = BUN_BUILTINS if tool == "bun" else NPM_BUILTINS
    if sub == "run":
        if len(positional) < 2:
            return Result(ref, OK, "lists scripts")
        script = positional[1]
        pkg = repo.package_json(base)
        if tool == "bun" and pkg is not None and script not in (pkg.get("scripts") or {}) and "." in script:
            return check_path(ref, repo, script, base)  # bun run file.ts
        return _script_check(ref, repo, base, script, tool)
    if sub in builtins:
        return Result(ref, OK, f"{tool} builtin")
    return _script_check(ref, repo, base, sub, tool)  # `pnpm build` / `yarn lint` run scripts


def _make(ref, repo, base, toks) -> Result:
    args = toks[1:]
    d = base
    targets = []
    i = 0
    makefile = None
    while i < len(args):
        a = args[i]
        if a == "-C" and i + 1 < len(args):
            d = os.path.join(base, args[i + 1])
            i += 2
            continue
        if a == "-f" and i + 1 < len(args):
            makefile = os.path.join(base, args[i + 1])
            i += 2
            continue
        if not a.startswith("-") and "=" not in a:
            targets.append(a)
        i += 1
    if makefile is None:
        for n in ("GNUmakefile", "makefile", "Makefile"):
            if os.path.isfile(os.path.join(d, n)):
                makefile = os.path.join(d, n)
                break
    if makefile is None or not os.path.isfile(makefile):
        return Result(ref, STALE, "`make` but no Makefile in " + (os.path.relpath(d, repo.root) if repo.inside(d) else d))
    known, includes = repo.make_targets(makefile)
    known = known or set()
    rel = os.path.relpath(makefile, repo.root)
    missing = [t for t in targets if t not in known and not os.path.exists(os.path.join(d, t))]
    if not missing:
        return Result(ref, OK, f"target(s) in {rel}" if targets else f"{rel} exists")
    if includes:
        return Result(ref, UNCHECKED, f"`{missing[0]}` not in {rel}, which includes other makefiles")
    real = sorted(t for t in known if not t.startswith(".") and "%" not in t and "$" not in t)
    close = difflib.get_close_matches(missing[0], real, n=1, cutoff=0.6)
    hint = f"did you mean `{close[0]}`?" if close else ("targets: " + ", ".join(real[:12]) if real else "")
    return Result(ref, STALE, f"no target `{missing[0]}` in {rel}", hint)


def _just(ref, repo, base, toks) -> Result:
    jf = repo.find_up(base, ["justfile", "Justfile", ".justfile"])
    if jf is None:
        return Result(ref, STALE, "`just` but no justfile found")
    positional = [a for a in toks[1:] if not a.startswith("-")]
    if not positional:
        return Result(ref, OK, "default recipe")
    recipes = repo.just_recipes(jf)
    if positional[0] in recipes:
        return Result(ref, OK, f"recipe in {os.path.relpath(jf, repo.root)}")
    close = difflib.get_close_matches(positional[0], sorted(recipes), n=1, cutoff=0.6)
    return Result(ref, STALE, f"no recipe `{positional[0]}` in {os.path.relpath(jf, repo.root)}",
                  f"did you mean `{close[0]}`?" if close else "")


def _module(ref, repo, base, mod) -> Result:
    parts = mod.split(".")
    rel = "/".join(parts)
    for root in (base, repo.root, os.path.join(repo.root, "src")):
        if os.path.isfile(os.path.join(root, rel + ".py")) or os.path.isfile(os.path.join(root, rel, "__init__.py")) \
                or os.path.isfile(os.path.join(root, rel, "__main__.py")):
            return Result(ref, OK, f"module `{mod}` found")
    for root in (base, repo.root, os.path.join(repo.root, "src")):
        top = os.path.join(root, parts[0])
        if os.path.isdir(top) or os.path.isfile(top + ".py"):
            return Result(ref, STALE, f"module `{mod}` not found in local package `{parts[0]}`")
    return Result(ref, UNCHECKED, f"`{mod}` is not a local module")


def _file_args(ref, repo, base, args) -> Result:
    checked = 0
    for a in args:
        if a.startswith("-") or "=" in a:
            continue
        a = a.split("::", 1)[0]
        if "/" in a or re.search(r"\.\w{1,4}$", a):
            r = check_path(ref, repo, a, base)
            if r.status != OK:
                return Result(ref, r.status, f"`{a}`: {r.reason}", r.hint)
            checked += 1
    return Result(ref, OK, "paths exist" if checked else "no file arguments to check")


def check_part(ref: Ref, repo: Repo, base: str, part: str) -> Result:
    toks = _tokens(part)
    if toks is None:
        return Result(ref, UNCHECKED, "could not parse")
    if not toks:
        return Result(ref, OK, "empty")
    head = toks[0]
    if head in ("npm", "pnpm", "yarn", "bun"):
        return _node_runner(ref, repo, base, toks)
    if head == "make":
        return _make(ref, repo, base, toks)
    if head == "just":
        return _just(ref, repo, base, toks)
    if head in ("python", "python3", "uv", "poetry"):
        args = toks[1:]
        if head in ("uv", "poetry"):
            if not args or args[0] != "run":
                return Result(ref, OK, f"{head} builtin")
            args = args[1:]
            if args and args[0] in ("python", "python3"):
                args = args[1:]
            elif args and args[0] in ("pytest",):
                return _file_args(ref, repo, base, args[1:])
            elif args and not args[0].startswith("-") and not args[0].endswith(".py"):
                return Result(ref, UNCHECKED, f"`{args[0]}` is a console script")
        if "-m" in args:
            i = args.index("-m")
            if i + 1 < len(args):
                if args[i + 1] == "pytest":
                    return _file_args(ref, repo, base, args[i + 2:])
                return _module(ref, repo, base, args[i + 1])
        if "-c" in args:
            return Result(ref, OK, "inline code")
        return _file_args(ref, repo, base, args[:1])
    if head in ("pytest", "tox", "nox"):
        return _file_args(ref, repo, base, toks[1:])
    if head in ("bash", "sh", "zsh", "node", "deno"):
        args = [a for a in toks[1:] if a not in ("run", "-e", "-c")]
        if "-c" in toks or "-e" in toks:
            return Result(ref, OK, "inline code")
        return _file_args(ref, repo, base, args[:1])
    if head in ("cargo",):
        if repo.find_up(base, ["Cargo.toml"]) is None:
            return Result(ref, STALE, "`cargo` but no Cargo.toml found")
        return Result(ref, OK, "Cargo.toml exists")
    if head == "go":
        if repo.find_up(base, ["go.mod", "go.work"]) is None:
            return Result(ref, STALE, "`go` but no go.mod found")
        return Result(ref, OK, "go.mod exists")
    if head.startswith("./") or ("/" in head and not head.startswith("/")):
        r = check_path(ref, repo, head, base)
        if r.status == OK and not os.access(os.path.join(base, head), os.X_OK) and os.path.isfile(os.path.join(base, head)):
            return Result(ref, STALE, f"`{head}` exists but is not executable", "chmod +x it, or call it with bash")
        return Result(ref, r.status, f"`{head}`: {r.reason}", r.hint)
    return Result(ref, UNCHECKED, f"`{head}` is not a runner stalemd knows")


def check_command(ref: Ref, repo: Repo) -> Result:
    base = ref.base
    worst: Optional[Result] = None
    for part in split_chain(ref.text):
        toks = _tokens(part) or []
        if toks[:1] == ["cd"] and len(toks) > 1:
            target = os.path.normpath(os.path.join(base, toks[1]))
            if not os.path.isdir(target):
                if repo.inside(target) and not repo.is_ignored(target, True):
                    return Result(ref, STALE, f"`cd {toks[1]}`: directory does not exist", repo.suggest_path(toks[1]))
                return Result(ref, UNCHECKED, f"`cd {toks[1]}` goes somewhere stalemd can't see")
            base = target
            continue
        if toks[:1] in (["npx"], ["pip"], ["pip3"], ["git"], ["echo"], ["export"], ["source"], ["."]):
            continue
        r = check_part(ref, repo, base, part)
        if r.status == STALE:
            return r
        if worst is None or (worst.status == OK and r.status == UNCHECKED):
            worst = r
    return worst or Result(ref, OK, "nothing to check")


def check(ref: Ref, repo: Repo) -> Result:
    if ref.kind == "path":
        return check_path(ref, repo)
    return check_command(ref, repo)
