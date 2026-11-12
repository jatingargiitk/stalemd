import os
import subprocess
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))


@pytest.fixture
def make_repo(tmp_path):
    """Create a git repo from a {path: content} dict and return its root."""

    def _make(files, git=True):
        for rel, content in files.items():
            p = tmp_path / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            if content is None:
                p.mkdir(exist_ok=True)
                continue
            p.write_text(content)
            if rel.endswith(".sh") and content.startswith("#!"):
                p.chmod(0o755)
        if git:
            subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
        return str(tmp_path)

    return _make
