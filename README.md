# stalemd

Find the commands, scripts and paths in `AGENTS.md`, `CLAUDE.md` and other agent instruction files that no longer exist in your repo.

Coding agents follow these files literally. When a script gets renamed, a Makefile target is dropped or a folder moves, the instructions keep telling the agent to run or read something that isn't there. stalemd reads the instruction files, pulls out every command and path they mention, and checks each one against the repo on disk. It doesn't run anything.

- Stdlib-only Python 3.9+, no dependencies.
- Works offline, on any repo.
- Comes with a GitHub Action that annotates the stale lines in a PR.

## Install

```bash
pip install git+https://github.com/jatingargiitk/stalemd
```

## Usage

Run it from anywhere inside a repo:

```bash
stalemd
```

This is the real output on [`examples/demo-repo`](examples/demo-repo), whose [`AGENTS.md`](examples/demo-repo/AGENTS.md) has drifted from the code:

```console
$ stalemd --root examples/demo-repo
STALE AGENTS.md:12  npm test
      no script `test` in package.json (did you mean `test:unit`?)
STALE AGENTS.md:13  make lint
      no target `lint` in Makefile (targets: check, setup)
STALE AGENTS.md:14  python -m app.worker
      module `app.worker` not found in local package `app`
STALE AGENTS.md:15  ./scripts/deploy.sh
      `./scripts/deploy.sh` exists but is not executable (chmod +x it, or call it with bash)
STALE AGENTS.md:18  src/api/routes.py
      path does not exist
STALE AGENTS.md:20  docs/adr/README.md
      path does not exist

1 instruction file(s), 16 reference(s): 6 stale, 8 ok, 2 unchecked
```

It exits with status 1 when anything is stale, so it can gate CI. Add `--no-fail` to only report.

`--all` also lists what checked out and what was skipped:

```console
$ stalemd --root examples/demo-repo --all
ok    AGENTS.md:5  make setup
      target(s) in Makefile
ok    AGENTS.md:6  npm install
      npm builtin
skip  AGENTS.md:7  cp .env.example .env
      `cp` is not a runner stalemd knows
ok    AGENTS.md:11  npm run dev
      script `dev` in package.json
STALE AGENTS.md:12  npm test
      no script `test` in package.json (did you mean `test:unit`?)
...
```

`--format json` prints every result with `file`, `line`, `kind`, `text`, `status`, `reason` and `hint`. `--format github` prints workflow annotations.

## What it checks

Files it finds by itself: `AGENTS.md`, `AGENT.md`, `CLAUDE.md`, `CLAUDE.local.md`, `GEMINI.md`, `.cursorrules`, `.windsurfrules`, `.clinerules`, `.github/copilot-instructions.md` and `.cursor/rules/*.mdc`, at any depth (skipping `node_modules`, `.venv` and similar). Pass file names to check specific files instead.

From those files it reads shell code blocks, inline code spans, relative Markdown links and Claude Code `@path` imports.

| Reference | Stale when |
| --- | --- |
| `npm run x`, `npm test`, `pnpm x`, `yarn x`, `bun run x` | the nearest `package.json` has no such script |
| `make x`, `make -C dir x` | the Makefile has no such target |
| `just x` | the justfile has no such recipe or alias |
| `python -m pkg.mod`, `uv run python -m ...` | `pkg` is a local package but `pkg/mod` isn't in it |
| `python file.py`, `pytest tests/x.py::test`, `bash x.sh`, `node x.js` | the file isn't there |
| `./scripts/x.sh` | the file isn't there, or isn't executable |
| `cd dir && ...` | `dir` doesn't exist; later commands are checked from inside it |
| `cargo ...`, `go ...` | there's no `Cargo.toml` or `go.mod` |
| paths, globs, links, `@imports` | nothing on disk matches |

To keep false alarms down it leaves some things as `unchecked` instead of `stale`:

- Paths that are missing but git-ignored, such as `.env` or `dist/`.
- Workspace-scoped commands like `pnpm --filter web build`.
- Makefiles that `include` other makefiles.
- Modules that aren't in the repo, like `python -m http.server`.
- Placeholders like `path/to/file.py`, and bare file names that may live outside the repo, like `settings.json`.
- Commands it doesn't know, like `docker compose up`.

A path written relative to a subfolder, like `src/cli/dev.ts` meaning `packages/next/src/cli/dev.ts`, counts as found. When a path is missing, stalemd suggests where a file with the same name lives now.

To skip a line on purpose, put `<!-- stalemd: ignore -->` on it, or alone on the line before it.

## GitHub Action

```yaml
name: stalemd
on: [pull_request]
jobs:
  stalemd:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: jatingargiitk/stalemd@main
```

Stale references show up as warnings on the lines in the PR diff, and the step fails. Inputs: `files` (space-separated files to check instead of discovering them) and `fail` (`"false"` to only annotate).

## Limits

stalemd checks that things exist, not that the instructions are right. A script can exist and still do something other than what the file says. It also doesn't follow npm workspaces or Makefile includes.

## License

MIT
