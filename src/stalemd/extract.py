"""Pull checkable references out of agent instruction files (AGENTS.md, CLAUDE.md, ...)."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from typing import Iterator, List, Optional

INSTRUCTION_NAMES = {
    "AGENTS.md",
    "AGENT.md",
    "CLAUDE.md",
    "CLAUDE.local.md",
    "GEMINI.md",
    ".cursorrules",
    ".windsurfrules",
    ".clinerules",
}
SKIP_DIRS = {".git", "node_modules", ".venv", "venv", "__pycache__", "dist", "build", "target", "vendor", ".tox"}

SHELL_LANGS = {"", "sh", "bash", "shell", "zsh", "console", "terminal", "shell-session", "fish", "cmd"}

# First words that make an inline code span a command rather than a path.
RUNNERS = {
    "npm", "pnpm", "yarn", "bun", "npx", "make", "just", "pytest", "python", "python3",
    "bash", "sh", "zsh", "node", "cargo", "go", "uv", "poetry", "tox", "nox", "deno", "pip", "pip3",
}

PATH_EXTS = {
    "md", "mdc", "txt", "py", "js", "mjs", "cjs", "ts", "tsx", "jsx", "json", "yaml", "yml", "toml",
    "sh", "rs", "go", "rb", "java", "kt", "swift", "c", "h", "cc", "cpp", "hpp", "cs", "php", "sql",
    "html", "css", "scss", "vue", "svelte", "lock", "cfg", "ini", "env", "proto", "graphql", "tf", "lua",
}

FENCE_RE = re.compile(r"^\s*(`{3,}|~{3,})\s*([\w+-]*)")
INLINE_CODE_RE = re.compile(r"(?<!`)`([^`\n]+)`(?!`)")
LINK_RE = re.compile(r"(?<!!)\[[^\]]*\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")
IMPORT_RE = re.compile(r"(?:^|\s)@((?:\.{1,2}/|[\w-]+/)*[\w.-]+\.\w{1,5})\b")
IGNORE_MARK = "stalemd: ignore"


@dataclass
class Ref:
    file: str  # instruction file, relative to root
    line: int
    kind: str  # "command" | "path"
    text: str
    base: str  # directory the reference is relative to (absolute)
    origin: str = "inline"  # "fence" | "inline" | "link" | "import"
    extra: dict = field(default_factory=dict)


def discover(root: str) -> List[str]:
    """Return instruction files under root, sorted, as absolute paths."""
    found = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS)
        rel = os.path.relpath(dirpath, root)
        for name in sorted(filenames):
            full = os.path.join(dirpath, name)
            if name in INSTRUCTION_NAMES:
                found.append(full)
            elif name == "copilot-instructions.md" and rel.replace(os.sep, "/").endswith(".github"):
                found.append(full)
            elif name.endswith(".mdc") and rel.replace(os.sep, "/").endswith(".cursor/rules"):
                found.append(full)
    return found


def looks_like_path(s: str) -> bool:
    s = s.strip()
    if not s or " " in s or s.startswith(("-", "http:", "https:", "mailto:", "~", "$", "/", "<")):
        return False
    if any(c in s for c in "(){}=<>,;|'\"\\") or "://" in s:
        return False
    if s.startswith("@"):
        return False  # npm scope or decorator
    stem = s.rstrip("/")
    last = stem.rsplit("/", 1)[-1]
    if "." in last and not last.startswith("."):
        ext = last.rsplit(".", 1)[-1].lower()
        if ext in PATH_EXTS:
            return True
        return False
    if "/" in stem:
        # dir/like/this  -- require every part to be a plain name
        parts = stem.split("/")
        return all(re.fullmatch(r"[\w.*-]+", p) for p in parts) and not all(p.isdigit() for p in parts)
    if s.endswith("/") and re.fullmatch(r"[\w.-]+/", s):
        return True
    if last.startswith(".") and re.fullmatch(r"\.[\w.-]+", last) and len(last) > 2:
        return True  # dotfiles like .env.example
    return False


def looks_like_command(s: str) -> bool:
    s = s.strip()
    if s.startswith("$ "):
        s = s[2:]
    first = s.split()[0] if s.split() else ""
    while "=" in first and not first.startswith("="):  # FOO=1 cmd
        rest = s.split(None, 1)
        if len(rest) < 2:
            return False
        s = rest[1]
        first = s.split()[0]
    return first in RUNNERS or first.startswith("./") or (first.endswith(".sh") and "/" in first)


def _strip_prompt(line: str) -> str:
    line = line.strip()
    if line.startswith("$ ") or line.startswith("> "):
        line = line[2:]
    return line


def extract(path: str, root: str) -> Iterator[Ref]:
    rel = os.path.relpath(path, root).replace(os.sep, "/")
    base = os.path.dirname(os.path.abspath(path))
    with open(path, encoding="utf-8", errors="replace") as fh:
        lines = fh.read().splitlines()

    fence: Optional[str] = None
    fence_lang = ""
    ignore_next = False
    for i, raw in enumerate(lines, 1):
        if IGNORE_MARK in raw:
            ignore_next = raw.strip().startswith("<!--")  # a comment on its own line covers the next line
            continue
        skip = ignore_next
        ignore_next = False

        m = FENCE_RE.match(raw)
        if fence is None and m:
            fence, fence_lang = m.group(1), m.group(2).lower()
            continue
        if fence is not None:
            if raw.strip().startswith(fence[0] * len(fence)) and raw.strip().strip(fence[0]) == "":
                fence = None
                continue
            if skip or fence_lang not in SHELL_LANGS:
                continue
            cmd = _strip_prompt(raw)
            if not cmd or cmd.startswith("#"):
                continue
            if fence_lang == "" and not looks_like_command(cmd):
                continue  # untagged fences are often prose or output; only take obvious commands
            yield Ref(rel, i, "command", cmd, base, "fence")
            continue
        if skip:
            continue

        for lm in LINK_RE.finditer(raw):
            target = lm.group(1)
            if target.startswith(("http:", "https:", "mailto:", "#", "tel:")) or "://" in target:
                continue
            target = target.split("#", 1)[0].split("?", 1)[0]
            if target:
                yield Ref(rel, i, "path", target, base, "link")
        no_code = INLINE_CODE_RE.sub(" ", raw)
        for im in IMPORT_RE.finditer(no_code):
            yield Ref(rel, i, "path", im.group(1), base, "import")
        for cm in INLINE_CODE_RE.finditer(raw):
            span = cm.group(1).strip()
            if looks_like_command(span):
                yield Ref(rel, i, "command", _strip_prompt(span), base, "inline")
            elif looks_like_path(span):
                yield Ref(rel, i, "path", span, base, "inline")
