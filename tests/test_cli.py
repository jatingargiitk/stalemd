import json
import os

from stalemd.cli import main

DEMO = os.path.join(os.path.dirname(__file__), "..", "examples", "demo-repo")


def test_demo_repo_text(capsys):
    code = main(["--root", DEMO])
    out = capsys.readouterr().out
    assert code == 1
    assert "STALE AGENTS.md:12  npm test" in out
    assert "did you mean `test:unit`?" in out
    assert "legacy/run.py" not in out  # ignored line
    assert "6 stale" in out


def test_demo_repo_json(capsys):
    main(["--root", DEMO, "--format", "json"])
    data = json.loads(capsys.readouterr().out)
    stale = sorted(r["text"] for r in data["results"] if r["status"] == "stale")
    assert stale == sorted([
        "npm test", "make lint", "python -m app.worker", "./scripts/deploy.sh",
        "src/api/routes.py", "docs/adr/README.md",
    ])


def test_github_annotations(capsys):
    main(["--root", DEMO, "--format", "github"])
    out = capsys.readouterr().out
    assert "::warning file=AGENTS.md,line=13,title=stalemd::make lint: no target `lint` in Makefile" in out


def test_no_fail_and_clean_repo(make_repo, capsys):
    assert main(["--root", DEMO, "--no-fail"]) == 0
    root = make_repo({"AGENTS.md": "Run `make test`.\n", "Makefile": "test:\n\techo\n"})
    assert main(["--root", root]) == 0
    assert "0 stale, 1 ok" in capsys.readouterr().out


def test_explicit_files_and_list(make_repo, capsys):
    root = make_repo({"docs/agent.md": "See `gone.md`.\n", "AGENTS.md": "fine\n"})
    assert main(["--root", root, "--list-files"]) == 0
    assert capsys.readouterr().out.strip() == "AGENTS.md"
    assert main(["--root", root, os.path.join(root, "docs/agent.md")]) == 1
    assert main(["--root", root, os.path.join(root, "nope.md")]) == 2
