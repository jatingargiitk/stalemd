import os

from stalemd.extract import discover, extract, looks_like_command, looks_like_path


def refs(make_repo, text, name="AGENTS.md"):
    root = make_repo({name: text})
    return [(r.kind, r.text, r.origin) for r in extract(os.path.join(root, name), root)]


def test_fenced_shell_lines_are_commands(make_repo):
    out = refs(make_repo, "```bash\n$ npm test\n# comment\nmake build\n```\n")
    assert out == [("command", "npm test", "fence"), ("command", "make build", "fence")]


def test_non_shell_fences_are_skipped(make_repo):
    assert refs(make_repo, "```python\nimport src.missing\n```\n```json\n{\"a\": \"b/c.json\"}\n```\n") == []


def test_untagged_fence_only_takes_obvious_commands(make_repo):
    out = refs(make_repo, "```\nsome output line\nnpm run lint\n```\n")
    assert out == [("command", "npm run lint", "fence")]


def test_inline_spans_links_and_imports(make_repo):
    out = refs(make_repo, "Run `pnpm lint`. Code in `src/app.py`. See [docs](docs/x.md#part) and @notes/style.md\n")
    assert ("command", "pnpm lint", "inline") in out
    assert ("path", "src/app.py", "inline") in out
    assert ("path", "docs/x.md", "link") in out
    assert ("path", "notes/style.md", "import") in out


def test_urls_and_anchors_are_not_paths(make_repo):
    out = refs(make_repo, "[a](https://x.com/a.md) [b](#heading) `https://example.com/x.py`\n")
    assert out == []


def test_ignore_comment_skips_next_line(make_repo):
    out = refs(make_repo, "<!-- stalemd: ignore -->\n`old/thing.py`\n`new/thing.py`\n")
    assert out == [("path", "new/thing.py", "inline")]


def test_ignore_comment_on_same_line(make_repo):
    assert refs(make_repo, "`old/thing.py` <!-- stalemd: ignore -->\n") == []


def test_path_heuristics():
    for good in ["src/app.py", "docs/", ".env.example", "packages/*", "README.md", "a/b/c"]:
        assert looks_like_path(good), good
    for bad in ["foo()", "e.g.", "v1.2.3", "--flag", "a = b", "~/.claude/x.md", "https://a.b/c.md", "@scope/pkg", "1/2"]:
        assert not looks_like_path(bad), bad


def test_command_heuristics():
    assert looks_like_command("NODE_ENV=test npm test")
    assert looks_like_command("./scripts/run.sh")
    assert looks_like_command("$ make")
    assert not looks_like_command("git status")
    assert not looks_like_command("useState")


def test_discover_finds_known_files(make_repo):
    root = make_repo({
        "AGENTS.md": "x",
        "pkg/CLAUDE.md": "x",
        ".github/copilot-instructions.md": "x",
        ".cursor/rules/style.mdc": "x",
        "node_modules/dep/AGENTS.md": "x",
        "docs/README.md": "x",
    })
    found = sorted(os.path.relpath(p, root) for p in discover(root))
    assert found == [".cursor/rules/style.mdc", ".github/copilot-instructions.md", "AGENTS.md", "pkg/CLAUDE.md"]
