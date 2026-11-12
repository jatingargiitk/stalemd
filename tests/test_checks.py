import json
import os

from stalemd.checks import OK, STALE, UNCHECKED, Repo, check
from stalemd.extract import Ref


def run(root, text, kind="command", base=None, origin="inline"):
    ref = Ref("AGENTS.md", 1, kind, text, base or root, origin)
    return check(ref, Repo(root))


PKG = json.dumps({"scripts": {"build": "tsc", "test:unit": "vitest", "lint": "eslint ."}})


def test_npm_scripts(make_repo):
    root = make_repo({"package.json": PKG})
    assert run(root, "npm run build").status == OK
    r = run(root, "npm test")
    assert r.status == STALE and "test:unit" in r.hint
    assert run(root, "npm install").status == OK
    assert run(root, "npm run nope").status == STALE


def test_pnpm_yarn_bun_shorthand(make_repo):
    root = make_repo({"package.json": PKG, "scripts/seed.ts": "x"})
    assert run(root, "pnpm lint").status == OK
    assert run(root, "yarn build").status == OK
    assert run(root, "pnpm typecheck").status == STALE
    assert run(root, "pnpm install").status == OK
    assert run(root, "bun test").status == OK
    assert run(root, "bun run scripts/seed.ts").status == OK


def test_workspace_scoped_is_unchecked(make_repo):
    root = make_repo({"package.json": PKG})
    assert run(root, "pnpm --filter=web build").status == UNCHECKED
    assert run(root, "npm run build -w web").status == UNCHECKED


def test_nearest_package_json_wins(make_repo):
    root = make_repo({"package.json": PKG, "web/package.json": json.dumps({"scripts": {"dev": "vite"}})})
    assert run(root, "npm run dev", base=os.path.join(root, "web")).status == OK
    assert run(root, "npm run dev").status == STALE


def test_missing_package_json(make_repo):
    root = make_repo({"README.md": "x"})
    r = run(root, "npm run build")
    assert r.status == STALE and "no package.json" in r.reason


def test_make_targets(make_repo):
    root = make_repo({"Makefile": ".PHONY: test\ntest: deps\n\tpytest\ndeps:\n\tpip install .\nX := 1\n"})
    assert run(root, "make test").status == OK
    assert run(root, "make").status == OK
    assert run(root, "make test VERBOSE=1").status == OK
    r = run(root, "make tset")
    assert r.status == STALE and "`test`" in r.hint
    assert run(root, "make X").status == STALE


def test_make_with_include_is_unchecked(make_repo):
    root = make_repo({"Makefile": "include common.mk\nbuild:\n\techo\n"})
    assert run(root, "make lint").status == UNCHECKED


def test_make_dash_c(make_repo):
    root = make_repo({"sub/Makefile": "run:\n\techo\n"})
    assert run(root, "make -C sub run").status == OK
    assert run(root, "make run").status == STALE


def test_just(make_repo):
    root = make_repo({"justfile": "default:\n  echo\n\ntest *args:\n  pytest {{args}}\nalias t := test\n"})
    assert run(root, "just test").status == OK
    assert run(root, "just t").status == OK
    assert run(root, "just deploy").status == STALE


def test_python_modules_and_files(make_repo):
    root = make_repo({"src/app/__init__.py": "", "src/app/cli.py": "", "tools/gen.py": ""})
    assert run(root, "python -m app.cli").status == OK
    assert run(root, "python -m app.worker").status == STALE
    assert run(root, "python -m http.server").status == UNCHECKED
    assert run(root, "python tools/gen.py --out x").status == OK
    assert run(root, "python3 tools/old.py").status == STALE
    assert run(root, "uv run python -m app.cli").status == OK
    assert run(root, "uv run ruff check").status == UNCHECKED


def test_pytest_paths(make_repo):
    root = make_repo({"tests/test_a.py": ""})
    assert run(root, "pytest tests/test_a.py::test_x -q").status == OK
    assert run(root, "pytest tests/test_b.py").status == STALE
    assert run(root, "python -m pytest tests").status == OK


def test_scripts_exist_and_are_executable(make_repo):
    root = make_repo({"scripts/ok.sh": "#!/bin/sh\necho\n", "scripts/noexec.sh": "echo\n"})
    assert run(root, "./scripts/ok.sh --fast").status == OK
    r = run(root, "./scripts/noexec.sh")
    assert r.status == STALE and "not executable" in r.reason
    assert run(root, "bash scripts/noexec.sh").status == OK
    assert run(root, "./scripts/gone.sh").status == STALE


def test_cd_chains(make_repo):
    root = make_repo({"web/package.json": json.dumps({"scripts": {"dev": "vite"}})})
    assert run(root, "cd web && npm run dev").status == OK
    assert run(root, "cd web && npm run build").status == STALE
    r = run(root, "cd frontend && npm run dev")
    assert r.status == STALE and "cd frontend" in r.reason


def test_cargo_and_go(make_repo):
    root = make_repo({"Cargo.toml": "[package]\n"})
    assert run(root, "cargo test").status == OK
    assert run(root, "go test ./...").status == STALE


def test_unknown_commands_are_unchecked(make_repo):
    root = make_repo({"README.md": ""})
    assert run(root, "docker compose up").status == UNCHECKED


def test_paths(make_repo):
    root = make_repo({"src/app.py": "", "docs/guide.md": "", ".gitignore": ".env\ndist/\n"})
    assert run(root, "src/app.py", "path").status == OK
    assert run(root, "src/*.py", "path").status == OK
    assert run(root, "src/*.rs", "path").status == STALE
    r = run(root, "src/api/app.py", "path")
    assert r.status == STALE
    assert run(root, "lib/app.py", "path").status == STALE
    assert "found at src/app.py" in run(root, "lib/app.py", "path").hint
    assert run(root, ".env", "path").status == UNCHECKED
    assert run(root, "dist/", "path").status == UNCHECKED
    assert run(root, "path/to/file.py", "path").status == UNCHECKED


def test_paths_relative_to_subdir_match_by_suffix(make_repo):
    root = make_repo({"packages/next/src/cli/dev.ts": ""})
    r = run(root, "src/cli/dev.ts", "path")
    assert r.status == OK and "packages/next/src/cli/dev.ts" in r.reason


def test_bare_names(make_repo):
    root = make_repo({".github/workflows/ci.yml": "", "README.md": ""})
    assert run(root, "ci.yml", "path").status == OK
    assert run(root, "settings.json", "path").status == UNCHECKED
    assert run(root, "CONTRIBUTING.md", "path").status == STALE
    assert run(root, "missing.json", "path", origin="link").status == STALE


def test_extensionless_non_paths_are_unchecked(make_repo):
    root = make_repo({"src/a.py": ""})
    assert run(root, "eslint/no-console", "path").status == UNCHECKED
    assert run(root, "src/api", "path").status == STALE
    assert run(root, "src/api/", "path").status == STALE


def test_paths_relative_to_instruction_dir(make_repo):
    root = make_repo({"pkg/lib/x.py": "", "pkg/CLAUDE.md": ""})
    assert run(root, "lib/x.py", "path", base=os.path.join(root, "pkg")).status == OK


def test_without_git_falls_back_to_skip_dirs(make_repo):
    root = make_repo({"src/a.py": ""}, git=False)
    assert run(root, "node_modules/x/index.js", "path").status == UNCHECKED
